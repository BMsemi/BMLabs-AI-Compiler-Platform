"""Verify bundled MNIST edge filters on the actual repository logical PE model.

This is a fixed sample validation, not a convolution compiler or digit classifier.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'compiler'))
from logical_pe import simulate, save


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    repo, out = Path(args.repo).resolve(), Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(repo))
    import numpy as np
    from bm_models.models.mnist import edge_filter, default_kernels, DEFAULT_DIR
    from bm_models.core.mapping import map_layer, LayerDims, PEGeometry
    kp, kn = default_kernels()
    kernels = [list(map(int, kernel.flat)) for kernel in (kp, kn)]
    ir = {'schema': 'bmlabs.linear-int8.v1', 'input_dtype': 'int8', 'output_dtype': 'int32',
          'weights': kernels, 'bias': [0, 0], 'relu': False}
    reports = []
    for digit in (5, 9):
        directory = out/str(digit)
        directory.mkdir()
        sample = DEFAULT_DIR/f'mnist{digit}_bin_28x28.txt'
        image = np.loadtxt(sample, dtype=int).tolist()
        vectors = []
        for y in range(28):
            for x in range(28):
                # Scalar window construction independent of upstream stride/einsum implementation.
                patch = [image[yy][xx] if 0 <= yy < 28 and 0 <= xx < 28 else 0
                         for yy in range(y-2, y+3) for xx in range(x-2, x+3)]
                vectors.append({'input': patch, 'expected': [sum(v*w for v, w in zip(patch, kernel)) for kernel in kernels]})
        save(directory/'ir.json', ir)
        save(directory/'vectors.json', vectors)
        report = simulate(ir, vectors, repo, directory)
        actual = json.loads((directory/'logical_pe_results.json').read_text())
        difference = [r['actual'][0]-r['actual'][1] for r in actual]
        expected = edge_filter({'digit': digit})
        if difference != [v for row in expected['map'] for v in row]:
            raise ValueError(f'MNIST {digit} PE output disagrees with upstream edge_filter.')
        save(directory/'upstream_edge_filter.json', expected)
        save(directory/'logical_edge_map.json', [difference[y*28:(y+1)*28] for y in range(28)])
        reports.append({'digit': digit, 'sample_sha256': hashlib.sha256(sample.read_bytes()).hexdigest(),
            'report': report, 'edge_map_comparisons': len(difference),
            'mapping': map_layer(LayerDims(K=2, C=1, R=5, S=5, Y=28, X=28), PEGeometry(32,32)).to_dict()})
    save(out/'mnist_verification.json', {'status': 'passed', 'samples': reports,
        'physical_hardware': False, 'scope': 'Two bundled binary MNIST edge-filter samples; no classifier, FPGA programming or general convolution lowering.'})
    print('BMLABS_MNIST_PE_PASS samples=2 column_comparisons=3136 edge_map_comparisons=1568')


if __name__ == '__main__':
    main()
