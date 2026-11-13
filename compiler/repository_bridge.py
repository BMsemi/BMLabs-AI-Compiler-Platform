"""Runs in the configured Torch interpreter, isolated from Django imports."""
import argparse
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from supported_model import parse_source, SCHEMA

def main():
    # The upstream exporter prints Unicode progress even with redirected output.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding='utf-8', errors='replace')
    p = argparse.ArgumentParser()
    p.add_argument('--repo', required=True)
    p.add_argument('--input', required=True)
    p.add_argument('--out', required=True)
    a = p.parse_args()
    repo = Path(a.repo).resolve()
    v2 = repo / 'projects/2_building_blocks/Neuromorphic_compiler_V2'
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    spec = parse_source(Path(a.input).read_text(encoding='utf-8'))
    sys.path.insert(0, str(repo))
    sys.path.insert(0, str(v2))
    import torch
    from torch import nn
    from compiler.preprocess_onnx import simplify
    from compiler.onnx_ir import ONNXIR
    from compiler.weight_quant import quantize
    from compiler.op_tiler import tile
    from compiler.mapping_assign import assign
    from maestro.dataflow_builder import build_layer_dataflows, render_maestro_network
    from maestro.Mapper import Mapper
    from maestro.Scheduler import Scheduler
    from runtime.global_memory_planner import GlobalMemoryPlanner
    from bm_models.core.mapping import map_layer, LayerDims, PEGeometry
    torch.set_num_threads(1)
    torch.manual_seed(0)
    rows, cols = len(spec['weights']), len(spec['weights'][0])
    linear = nn.Linear(cols, rows, bias=True)
    with torch.no_grad():
        linear.weight.copy_(torch.tensor(spec['weights'], dtype=torch.float32))
        linear.bias.copy_(torch.tensor(spec['bias'], dtype=torch.float32))
    model = nn.Sequential(OrderedDict([('linear', linear)] + ([('relu', nn.ReLU())] if spec['relu'] else [])))
    example = torch.zeros(1, cols)
    bundle = simplify(model, example, out / 'fx_graph.json')
    if bundle['onnx_status']['status'] == 'generated':
        import onnx
        exported = onnx.load(bundle['onnx_path'])
        onnx.checker.check_model(exported, full_check=True)
        (out/'onnx_validation.json').write_text(json.dumps({
            'status': 'passed', 'onnx_version': onnx.__version__,
            'ir_version': exported.ir_version,
            'opsets': {item.domain: item.version for item in exported.opset_import},
            'check': 'onnx.checker.check_model(full_check=True)'}, indent=2), encoding='utf-8')
    bundle['graph_module'].graph.lint()
    ir = ONNXIR(bundle, model, example)
    quantize(ir)
    qmeta = ir.quantized_weights['linear']
    qweight = torch.clamp(torch.round(linear.weight.detach() / qmeta['scale']), -127, 127).to(torch.int8).tolist()
    if min(map(min, qweight)) != qmeta['min_int8'] or max(map(max, qweight)) != qmeta['max_int8']:
        raise ValueError('Materialized weights disagree with upstream quantization metadata.')
    tile(ir)
    mapping = assign(ir)
    descriptors = build_layer_dataflows(ir)
    mapped = Mapper(mapping, descriptors).map()
    schedule = Scheduler(mapped, descriptors).schedule()
    plan = GlobalMemoryPlanner(schedule).plan()
    if not schedule or sum(t['tile_channels'] for t in schedule) != rows:
        raise ValueError('V2 schedule does not cover all output channels.')
    coverage = [channel for t in mapping['tiles'] for channel in range(t['channel_start'], t['channel_end'])]
    if sorted(coverage) != list(range(rows)):
        raise ValueError('V2 mapping has missing or duplicated output channels.')
    expected_tiles = {(t['module_name'], t['tile_index']) for t in mapping['tiles']}
    scheduled_tiles = [(t['module_name'], t['tile_index']) for t in schedule]
    if len(set(scheduled_tiles)) != len(scheduled_tiles) or set(scheduled_tiles) != expected_tiles:
        raise ValueError('V2 schedule has missing or duplicated tiles.')
    memory_ranges = sorted((v['address'], v['address'] + v['size_bytes']) for v in plan['layout'].values())
    if len(memory_ranges) != len(schedule) or any(start < 0 or end <= start for start, end in memory_ranges) or any(a[1] > b[0] for a, b in zip(memory_ranges, memory_ranges[1:])):
        raise ValueError('V2 prototype memory plan has invalid or overlapping allocations.')
    lowered = dict(schema=SCHEMA, input_dtype='int8', output_dtype='int32', weights=qweight,
        bias=spec['bias'], relu=spec['relu'], quantization=qmeta,
        semantics='Integer accumulator units; bias is not rescaled. No dequantization or X2 ABI binding.')
    outputs = {'ir.json': lowered, 'quantization.json': ir.quantized_weights,
        'mapping.json': mapping, 'schedule.json': schedule, 'memory_plan.json': plan,
        'dataflows.json': descriptors,
        'bmsemi_mapping.json': map_layer(LayerDims(K=rows, C=cols), PEGeometry(rows=32, cols=32)).to_dict()}
    for name, payload in outputs.items():
        (out/name).write_text(json.dumps(payload, indent=2), encoding='utf-8')
    (out/'dataflow.m').write_text(render_maestro_network(descriptors, 'LinearMilestone'), encoding='utf-8')
    imported = {}
    for name, module in list(sys.modules.items()):
        file = getattr(module, '__file__', None)
        if file and Path(file).suffix == '.py' and Path(file).resolve().is_relative_to(repo):
            imported[str(Path(file).resolve().relative_to(repo))] = hashlib.sha256(Path(file).read_bytes()).hexdigest()
    (out/'repository_modules.json').write_text(json.dumps(imported, indent=2), encoding='utf-8')
    print(json.dumps({'stage':'v2_capture_and_planning', 'torch':torch.__version__,
        'fx_nodes':len(ir.nodes), 'schedule_entries':len(schedule), 'onnx':bundle['onnx_status'],
        'scope':'generic Linear RTL; prototype planning estimates, no physical hardware mapping'}))

if __name__ == '__main__':
    main()
