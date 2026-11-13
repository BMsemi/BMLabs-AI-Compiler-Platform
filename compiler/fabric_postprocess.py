"""Versioned prototype FABulous postprocessor for signed int32 X2 results.

Byte command ABI v1: io_in[15:11]=output index, [10:8]=opcode,
[7:0]=data. Opcodes: 1 reset, 2 shift input byte (LSB first),
3 bias/ReLU, 4 shift result byte. io_out[7:0] is the result byte.
The shell pulses each command for exactly one fabric clock.
"""
from .supported_model import validate_ir


def emit(ir):
    model=validate_ir(ir)
    bias='\n'.join(f"5'd{i}: bias = {'-' if b<0 else ''}32'sd{abs(b)};" for i,b in enumerate(model['bias']))
    operation="sum[31] ? 32'd0 : sum" if model['relu'] else 'sum'
    return f'''module model_postprocess(input wire clk, input wire [15:0] io_in,
output wire [15:0] io_out, output wire [15:0] io_oeb);
reg signed [31:0] raw_value;
reg [31:0] result;
reg signed [31:0] bias;
wire signed [31:0] sum = raw_value + bias;
always @* begin
  bias=0;
  case (io_in[15:11])
{bias}
  default: bias=0;
  endcase
end
always @(posedge clk) begin
  case(io_in[10:8])
  3'd1: begin raw_value<=0;result<=0;end
  3'd2: raw_value<={{io_in[7:0],raw_value[31:8]}};
  3'd3: result<={operation};
  3'd4: result<={{8'd0,result[31:8]}};
  default: begin end
  endcase
end
assign io_out={{8'd0,result[7:0]}};
assign io_oeb=16'd0;
endmodule
'''
