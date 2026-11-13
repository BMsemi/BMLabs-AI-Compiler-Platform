"""Frontend-independent contracts. No input code is executed by the web process."""
from dataclasses import dataclass, field
from typing import Protocol, Any

IR_SCHEMA_VERSION = '1.0'

@dataclass(frozen=True)
class TensorSpec:
    name: str
    shape: tuple[int, ...]
    dtype: str

@dataclass(frozen=True)
class GraphNode:
    id: str
    operator: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    attributes: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class GraphIR:
    inputs: tuple[TensorSpec, ...]
    outputs: tuple[TensorSpec, ...]
    nodes: tuple[GraphNode, ...]
    schema_version: str = IR_SCHEMA_VERSION

    def validate(self):
        if self.schema_version != IR_SCHEMA_VERSION:
            raise ValueError('Unsupported IR schema version.')
        tensors = (*self.inputs, *self.outputs)
        if any(not t.name or not t.shape or any(type(d) is not int or d <= 0 for d in t.shape) for t in tensors):
            raise ValueError('Tensor names and positive static dimensions are required.')
        if any(t.dtype not in {'int8', 'uint8', 'int16', 'int32', 'float16', 'float32'} for t in tensors):
            raise ValueError('Unsupported tensor type.')
        names = [t.name for t in self.inputs]
        if len(set(names)) != len(names):
            raise ValueError('Input names must be unique.')
        available = set(names)
        ids = set()
        for node in self.nodes:
            if not node.id or node.id in ids or not node.operator or not node.outputs:
                raise ValueError('Nodes require unique IDs, operators and outputs.')
            if not set(node.inputs) <= available:
                raise ValueError('Graph must be ordered and all inputs defined.')
            if len(set(node.outputs)) != len(node.outputs) or available.intersection(node.outputs):
                raise ValueError('Graph outputs must be unique.')
            ids.add(node.id)
            available.update(node.outputs)
        if not {t.name for t in self.outputs} <= available:
            raise ValueError('Graph outputs must be defined.')

@dataclass(frozen=True)
class CompileRequest:
    build_id: str
    input_manifest: tuple[dict, ...]
    target_profile: dict
    configuration: dict
    x2_abi: dict

@dataclass(frozen=True)
class StageReport:
    stage: str
    passed: bool
    evidence: tuple[str, ...]
    metrics: dict = field(default_factory=dict)

class CompilerAdapter(Protocol):
    version: str
    def lower(self, request: CompileRequest) -> GraphIR: ...
    def map(self, graph: GraphIR, target: dict, x2_abi: dict) -> dict: ...

class RTLProvider(Protocol):
    def generate(self, graph: GraphIR, mapping: dict, x2_abi: dict) -> bytes: ...

class FabricAdapter(Protocol):
    def synthesize(self, rtl: bytes, target: dict) -> StageReport: ...
    def place_and_route(self, netlist: bytes, target: dict) -> StageReport: ...
    def bitstream(self, fasm: bytes, target: dict) -> bytes: ...

class X2Adapter(Protocol):
    def cosimulate(self, bitstream: bytes, abi: dict, oracle: dict) -> StageReport: ...

class ImplementationVerifier(Protocol):
    def verify(self, stage: str, request: CompileRequest, artifacts: dict) -> StageReport: ...

class DeploymentAdapter(Protocol):
    def program(self, device_id: str, bitstream: bytes, target: dict) -> StageReport: ...
