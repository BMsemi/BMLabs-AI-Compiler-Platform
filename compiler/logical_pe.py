"""Run the repository's cycle-stepped PE model; never encode hardware configuration."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from supported_model import validate_ir

GEOMETRY = {'rows': 32, 'cols': 32}


def save(path, value):
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')


def simulate(ir, vectors, repo, out):
    """Transpose KxC model weights into 32 input rows x 32 output columns."""
    ir = validate_ir(ir)
    sys.path.insert(0, str(repo))
    from bm_models.core.mapping import LayerDims, PEGeometry, map_layer
    from bm_models.vendor.neuromorphic_x1.neuromorphic_x2 import NeuromorphicX2
    n, k = len(ir['weights'][0]), len(ir['weights'])
    mapping = map_layer(LayerDims(K=k, C=n), PEGeometry(**GEOMETRY)).to_dict()
    if mapping['pe_tiles'] != 1 or mapping['fold_sizes'] != [n] or mapping['k_chunks'] != [(0, k)]:
        raise ValueError('Repository mapping does not cover this single logical PE tile.')
    weights = [[ir['weights'][col][row] if row < n and col < k else 0
                for col in range(32)] for row in range(32)]
    save(out/'logical_pe_mapping.json', {
        'schema': 'bmlabs.logical-pe.v1', 'geometry': GEOMETRY, 'mapping': mapping,
        'weights_input_rows_output_columns': weights,
        'active_inputs': n, 'active_outputs': k,
        'postprocessing': {'bias': ir['bias'], 'relu': ir['relu'], 'location': 'adapter'},
        'scope': 'Logical software mapping, not physical placement or a bitstream.'})
    chip = NeuromorphicX2(iterations=0, input_size=32, output_size=32)
    chip.program_weights(weights)
    results = []
    if not vectors:
        raise ValueError('No independent oracle vectors supplied.')
    for index, vector in enumerate(vectors):
        x, expected = vector['input'], vector['expected']
        if len(x) != n or len(expected) != k:
            raise ValueError('Oracle vector dimensions do not match IR.')
        if any(type(v) is not int or not -128 <= v <= 127 for v in x):
            raise ValueError('Oracle input must be signed int8.')
        chip.load_inputs(x + [0] * (32 - n))
        chip.command(chip.COMPUTE)
        chip.run_until_idle(max_cycles=1000)
        raw = chip.read_outputs().tolist()
        if len(raw) != 32 or any(v != int(v) for v in raw) or any(raw[k:]):
            raise ValueError(f'Invalid PE output or nonzero unused column at vector {index}.')
        actual = [int(raw[j]) + ir['bias'][j] for j in range(k)]
        if ir['relu']:
            actual = [max(0, v) for v in actual]
        results.append({'input': x, 'raw_mvm': raw, 'actual': actual, 'expected': expected})
        if actual != expected:
            save(out/'logical_pe_results.json', results)
            raise ValueError(f'Logical PE numerical mismatch at vector {index}: {actual} != {expected}')
    save(out/'logical_pe_results.json', results)
    sources = {}
    for module in list(sys.modules.values()):
        path = getattr(module, '__file__', None)
        if path and Path(path).suffix == '.py' and Path(path).resolve().is_relative_to(repo):
            sources[str(Path(path).resolve().relative_to(repo))] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    save(out/'logical_pe_sources.json', sources)
    report = {'status': 'passed', 'physical_hardware': False, 'geometry': GEOMETRY,
              'vectors': len(vectors), 'outputs': k, 'comparisons': len(vectors) * k,
              'stage_cycles': chip.stage_cycles, 'total_modeled_cycles': chip.cycle,
              'output_buffer_words': chip.output_buffer_words,
              'scope': 'Repository cycle-stepped ideal arithmetic; adapter applies bias/ReLU. No X2 ABI, clock frequency, physical fabric or loader assumed.'}
    save(out/'logical_pe_verification.json', report)
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--repo', required=True)
    p.add_argument('--ir', required=True)
    p.add_argument('--vectors', required=True)
    p.add_argument('--out', required=True)
    args = p.parse_args()
    report = simulate(json.loads(Path(args.ir).read_text()), json.loads(Path(args.vectors).read_text()),
                      Path(args.repo).resolve(), Path(args.out))
    print(f"BMLABS_LOGICAL_PE_PASS vectors={report['vectors']} outputs={report['outputs']}")


if __name__ == '__main__':
    main()
