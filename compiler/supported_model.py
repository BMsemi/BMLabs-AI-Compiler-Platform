"""Parse a deliberately bounded Python data format; never execute user source."""
import ast
import math

SCHEMA = 'bmlabs.linear-int8.v1'

def parse_source(source):
    if len(source.encode('utf-8')) > 65536:
        raise ValueError('Model source exceeds the 64 KiB milestone limit.')
    tree = ast.parse(source)
    body = [n for n in tree.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))]
    if len(body) != 1 or not isinstance(body[0], ast.Assign) or len(body[0].targets) != 1 or not isinstance(body[0].targets[0], ast.Name) or body[0].targets[0].id != 'MODEL':
        raise ValueError('Supported Python is one literal MODEL = {...} assignment. Imports, calls and executable statements are unsupported.')
    if sum(1 for _ in ast.walk(tree)) > 5000:
        raise ValueError('Model specification is too complex.')
    model = ast.literal_eval(body[0].value)
    if not isinstance(model, dict) or set(model) != {'schema', 'weights', 'bias', 'relu'} or model['schema'] != SCHEMA:
        raise ValueError(f'Expected schema {SCHEMA}, weights, bias and relu only.')
    weights = model['weights']
    if not isinstance(weights, list) or not 1 <= len(weights) <= 32:
        raise ValueError('Expected 1–32 output rows.')
    if not isinstance(weights[0], list) or not 1 <= len(weights[0]) <= 32:
        raise ValueError('Expected 1–32 input columns.')
    n = len(weights[0])
    for row in weights:
        if not isinstance(row, list) or len(row) != n or any(type(v) not in (int, float) or abs(v) > 127 or not math.isfinite(v) for v in row):
            raise ValueError('Weights must be a rectangular finite matrix in [-127,127].')
    if not isinstance(model['bias'], list) or len(model['bias']) != len(weights) or any(type(v) is not int or abs(v) > 1048576 for v in model['bias']):
        raise ValueError('One integer accumulator bias per output is required, bounded by 2^20.')
    if type(model['relu']) is not bool:
        raise ValueError('relu must be True or False.')
    return model

def validate_ir(ir):
    if ir.get('schema') != SCHEMA or ir.get('input_dtype') != 'int8' or ir.get('output_dtype') != 'int32':
        raise ValueError('Unsupported lowered IR contract.')
    data = {k: ir[k] for k in ['schema', 'weights', 'bias', 'relu']}
    parse_source('MODEL = ' + repr(data))
    if any(type(w) is not int for row in data['weights'] for w in row):
        raise ValueError('RTL weights must be quantized integers.')
    return data
