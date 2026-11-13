"""Read-only hardware discovery and an executable candidate X2 source check.

This does not invent an ABI, a physical fabric profile, or a bitstream protocol.
"""
import hashlib
from pathlib import Path
from django.conf import settings
from .execution import run_command, wsl_command, wsl_path, write_json
from .synthesis import tool_command


def prototype_scope():
    """Describe separate software and board contracts without probing/programming a device."""
    runner = Path(settings.COMPILER_MODEL_REPO)/'hardware/zcu106_runner.py'
    from .physical_target import summary
    physical = summary()
    return {
        'configured_physical_target': physical,
        'physical_linear': {'pipeline':'linear-fpga-v1',
            'enabled':physical.get('programming_enabled',False),
            'scope':'Pinned Qwen6 overlay: PL signed int8 MVM and PS bias/ReLU, verified against independent model vectors.',
            'result_source':'Each build records actual programming and numerical evidence; configuration alone is not a test result.',
            'accepts_generated_fabulous_bitstream':False},
        'logical_pe': {'rows': 32, 'cols': 32, 'kind': 'logical',
            'pipelines': ['linear-int8-v1', 'linear-synth-v1'],
            'verification': 'Repository cycle-stepped PE vs the independent RTL oracle vectors',
            'physical_fabric_dimensions': None},
        'zcu106_self_test': {'status': 'preflight_configured' if physical['configured'] else 'not_connected', 'executed': False,
            'source_available': runner.is_file(), 'source_path': str(runner),
            'source_sha256': hashlib.sha256(runner.read_bytes()).hexdigest() if runner.is_file() else None,
            'scope': 'Existing runner supports one core.pe_self_test node using a fixed Qwen6 overlay.',
            'requires': ['Reachable ZCU106 board execution service or transport',
                'PYNQ interpreter and installed /home/xilinx/qwen6_20261005 assets'],
            'accepts_generated_fabulous_bitstream': False},
        'sky130_reram': {'pipeline':'sky130-counter-v1',
            'source_url':'https://github.com/mole99/sky130-reram-fpga/tree/main/user_designs',
            'revision':'e0790eb11a1e95914f2beb8f175396a0924144ed',
            'fabric':'classic_fabric_reram','configuration_rows':20,'configuration_columns':21,
            'scope':'Pinned upstream counter compilation; routing data, constraints and bitstream specification supplied by the repository.',
            'hardware_verified':False,'accepts_python_models':False},
        'physical_integration': {'status': 'unfinalized',
            'open_details': ['Board binding for the supplied SKY130 fabric', 'Validated operating clock and timing corner',
                'X2 host register map', 'Verified board bitstream loader interface'],
            'blocks': ['SKY130 fabric physical deployment', 'SKY130 ReRAM numerical co-simulation',
                'Loading generated FABulous binaries onto BM hardware'],
            'does_not_block': ['Logical 32x32 PE simulation', 'Generic RTL verification',
                'Upstream FABulous reference bitstream simulation', 'SKY130 upstream counter bitstream compilation']}}


def fabulous_preflight(target=None):
    from .inventory import current
    missing = []
    inventory = current()
    for key in ['fabulous', 'fabulous_yosys', 'fabulous_nextpnr']:
        if not inventory.get('tools', {}).get(key, {}).get('successful'):
            missing.append(key + ' has not passed its configured runtime probe')
    if not target or target.status != 'validated':
        missing.append('Validated BM FABulous target profile')
    if not target or not target.fabric_revision:
        missing.append('Frozen fabric revision, fabric.csv, BEL/PIP models and constraints')
    if not target or not target.bitstream_format:
        missing.append('Versioned FASM/bitstream encoding and configuration protocol')
    return {'status': 'unsupported', 'executed': False, 'missing': missing,
        'tools_ready': inventory.get('fabulous_tools_ready', False),
        'scope': 'BM hardware target only; an upstream reference run does not validate this target.',
        'detail': 'No target-specific FABulous command sequence is configured. No bitstream was generated.'}


def inspect_x2(out):
    out.mkdir(parents=True, exist_ok=False)
    root = Path(settings.COMPILER_X1_REPO)
    source_dir = root/'Neuromorphic_X2_32x32_updating_SRAM/Neuromorphic_X2_with_SRAM'
    sources = ['Neuromorphic_X2_Beh.v', 'Neuromorphic_X2_wb_tb.v']
    report = {'scope': 'Standalone candidate X2 source check, not compiler/fabric co-simulation',
        'source_root': str(root), 'source_hashes': {}, 'commands': [], 'status': 'unavailable',
        'limitations': ['The existing testbench has no independent numerical scoreboard.',
            'No finalized X2 ABI, compiler lowering or FABulous interconnect contract is configured.']}
    for name in sources:
        path = source_dir/name
        if not path.is_file():
            report['missing'] = str(path)
            return report
        data = path.read_bytes()
        (out/name).write_bytes(data)
        report['source_hashes'][name] = hashlib.sha256(data).hexdigest()
    argv = tool_command('IVERILOG', ['-g2012', '-Wall',
        '-s', 'Neuromorphic_X2_wb_tb', '-o', 'x2.vvp', *sources], out)
    compiled = run_command(argv, out, 90)
    report['commands'].append({'stage': 'candidate_x2_compile', **compiled})
    report['status'] = 'compiled' if compiled['successful'] else 'compile_failed'
    if compiled['successful']:
        simulated = run_command(tool_command('VVP', ['-n', 'x2.vvp'], out, timeout=15), out, 30)
        report['commands'].append({'stage': 'candidate_x2_simulation', **simulated})
        report['status'] = 'simulation_exited_unverified' if simulated['successful'] else 'simulation_failed'
    write_json(out/'x2-inspection.json', report)
    return report
