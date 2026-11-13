"""New generic combinational Linear backend; does not target X2 or FABulous."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from supported_model import validate_ir

def emit(ir):
    m = validate_ir(ir)
    n, k = len(m['weights'][0]), len(m['weights'])
    ports = [f'input wire signed [7:0] x{i}' for i in range(n)] + [f'output wire signed [31:0] y{j}' for j in range(k)]
    lines = ['// Generic int8 inputs/weights, int32 accumulator; no X2/FABulous ABI.', 'module linear_model(\n  ' + ',\n  '.join(ports) + '\n);']
    def lit(x):
        return f"-32'sd{-x}" if x < 0 else f"32'sd{x}"
    for j, row in enumerate(m['weights']):
        terms = []
        for i, w in enumerate(row):
            lines.append(f'wire signed [31:0] p{j}_{i} = $signed(x{i}) * ({lit(w)});')
            terms.append(f'p{j}_{i}')
        lines.append(f"wire signed [31:0] acc{j} = {lit(m['bias'][j])} + " + ' + '.join(terms) + ';')
        expression = f"(acc{j} < 0) ? 32'sd0 : acc{j}" if m['relu'] else f'acc{j}'
        lines.append(f'assign y{j} = {expression};')
    return '\n'.join(lines + ['endmodule', ''])

if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--ir',required=True); p.add_argument('--out',required=True); a=p.parse_args()
    Path(a.out).write_text(emit(json.loads(Path(a.ir).read_text())), encoding='utf-8')
    print('Generated generic combinational Verilog from validated quantized IR.')
