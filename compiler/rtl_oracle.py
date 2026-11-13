"""Independent scalar integer oracle and self-checking Icarus testbench."""
import argparse
import json
from pathlib import Path
import random
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from supported_model import validate_ir

def generate(ir, out):
    m=validate_ir(ir); n=len(m['weights'][0]); k=len(m['weights'])
    vectors=[[v]*n for v in [-128,-127,-1,0,1,126,127]]
    for i in range(n):
        for v in [-128,-1,1,127]:
            x=[0]*n; x[i]=v; vectors.append(x)
    rng=random.Random(20261103)
    vectors += [[rng.randrange(-128,128) for _ in range(n)] for _ in range(256)]
    tests=[]
    for x in vectors:
        y=[b + sum(a*w for a,w in zip(x,row)) for row,b in zip(m['weights'],m['bias'])]
        if m['relu']: y=[max(0,v) for v in y]
        if any(not -(2**31)<=v<2**31 for v in y): raise ValueError('Oracle accumulator overflow.')
        tests.append({'input':x,'expected':y})
    (out/'vectors.json').write_text(json.dumps(tests,indent=2),encoding='utf-8')
    lines=['`timescale 1ns/1ps','module tb;']
    lines += [f'reg signed [7:0] x{i};' for i in range(n)]
    lines += [f'wire signed [31:0] y{j};' for j in range(k)]
    lines += ['linear_model dut('+','.join([f'.x{i}(x{i})' for i in range(n)]+[f'.y{j}(y{j})' for j in range(k)])+');','initial begin']
    for idx,t in enumerate(tests):
        lines += [f"x{i} = 8'h{v & 255:02x};" for i,v in enumerate(t['input'])]
        lines.append('#1;')
        for j,v in enumerate(t['expected']):
            lines.append(f'if (y{j} !== 32\'h{v & 0xffffffff:08x}) $fatal(1,"FAIL vector={idx} output={j} actual=%d",y{j});')
    lines += [f'$display("BMLABS_RTL_PASS vectors={len(tests)} outputs={k}");','$finish;','end','initial begin #100000; $fatal(1,"TIMEOUT"); end','endmodule']
    (out/'tb.v').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (out/'verification_plan.json').write_text(json.dumps({'vectors':len(tests),'outputs':k,'seed':20261103,'coverage':'boundary, basis and random; not formal equivalence'}),encoding='utf-8')
    print(f'Generated independent scalar oracle for {len(tests)} vectors, {k} outputs.')

if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--ir',required=True); p.add_argument('--out',required=True); a=p.parse_args()
    generate(json.loads(Path(a.ir).read_text()),Path(a.out))
