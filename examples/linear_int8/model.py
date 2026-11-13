"""Supported Python model specification, parsed as data and never imported.
Inputs are signed int8; outputs are int32 quantized accumulator units.
This example's maximum absolute weight is 127, making its quantization scale 1.
"""
MODEL = {
    'schema': 'bmlabs.linear-int8.v1',
    'weights': [[127, -64, 2, 0], [-127, 0, 31, 1]],
    'bias': [3, -7],
    'relu': True,
}
