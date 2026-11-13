STAGES = [
    ('python', 'Python input', 'Store source and model files in a project workspace.'),
    ('golden', 'Golden validation', 'Independent numerical reference and tolerance checks.'),
    ('ir', 'Typed graph IR', 'Versioned tensors, operators and graph validation.'),
    ('mapping', 'Logical 32×32 PE mapping', 'Run V2 planning and the repository PE simulator against independent vectors; physical target details remain open.'),
    ('rtl', 'RTL generation', 'Configurable model provider and revision history.'),
    ('verification', 'RTL verification', 'Lint, simulation, assertions and equivalence checks.'),
    ('fabulous', 'FABulous implementation', 'Yosys synthesis, nextpnr routing and bitstream generation.'),
    ('bitstream', 'Bitstream verification', 'V0–V4 verification of the actual configured fabric.'),
    ('x2', 'X2 verification', 'Candidate Wishbone regression and numerical scoreboard; fabric co-simulation awaits the target and ABI.'),
    ('deployment', 'Hardware deployment', 'Device programming and silicon validation.'),
]

def capabilities():
    from django.conf import settings
    from .inventory import current
    snapshot = current()
    from .physical_target import summary
    physical = summary()
    return [{'id': key, 'name': name, 'description': description,
             'status': ('linear_pipeline' if settings.COMPILER_ENABLED and key in {'golden', 'ir', 'mapping', 'rtl', 'verification'}
                        else 'reference_pipeline' if settings.COMPILER_ENABLED and snapshot.get('fabulous_tools_ready') and key in {'fabulous', 'bitstream'}
                        else 'candidate_regression' if settings.COMPILER_ENABLED and key == 'x2'
                        else 'physical_pipeline' if settings.COMPILER_ENABLED and key == 'deployment' and physical.get('programming_enabled')
                        else 'board_preflight' if key == 'deployment' and physical['configured']
                        else 'storage_ready' if key == 'python' else 'not_connected'),
             'scope': ('Source-pinned binary-weight behavioral regression only; finalized ABI and fabric co-simulation unavailable.' if key == 'x2'
                       else 'Upstream reference counter flow available when runtime probes pass. BM implementation still requires its fabric package and loader contract.' if key in {'fabulous', 'bitstream'}
                       else ('One build verifies RTL and synthesis, checks the board, programs the pinned Qwen6 overlay and compares real PL MVM + PS bias/ReLU outputs with the oracle. Generated FABulous loading is a separate prototype.' if physical.get('programming_enabled') else 'ZCU106 read-only check only; programming disabled.') if key == 'deployment' else ''),
             'synthesis_available': bool(snapshot.get('synthesis_ready')) if key == 'verification' else None} for key, name, description in STAGES]

class IntegrationUnavailable(Exception):
    pass

def get_adapter(stage):
    if stage in ('linear-int8-v1', 'linear-synth-v1', 'linear-fpga-v1', 'x2-candidate-v1', 'fabulous-reference-v1', 'zcu106-preflight-v1', 'sky130-counter-v1'):
        from builds.runner import execute
        return execute
    if stage == 'x2-source-inspection':
        from .hardware import inspect_x2
        return inspect_x2
    if stage == 'fabulous-preflight':
        from .hardware import fabulous_preflight
        return fabulous_preflight
    raise IntegrationUnavailable(f'{stage} is unsupported. Select linear-int8-v1 for generic RTL; FABulous and X2 co-simulation need validated target contracts.')
