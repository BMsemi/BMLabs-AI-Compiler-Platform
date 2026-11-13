"""Independent, source-pinned candidate X2 regression (not a finalized ABI)."""
import difflib
import hashlib
import json
from pathlib import Path
import random
from django.conf import settings
from .execution import wsl_command, wsl_path, write_json
from .synthesis import tool_command


def candidate_patch(source):
    """Small reviewable fixes on a private copy, leaving the repository intact."""
    replacements = [
        ('wire        ip_full_io;', '''wire        ip_full_io;
  wire result_valid;
  wire [31:0] result_data;
  wire write_ack;
  wire selected = wbs_cyc_i && wbs_stb_i && wbs_adr_i == ADDR_MATCH && wbs_sel_i == 4'hf;
  wire result_ready = selected && !wbs_we_i && result_valid;
  assign wbs_dat_o = result_data;
  assign wbs_ack_o = wbs_we_i ? write_ack : result_ready;'''),
        ('.ip_full_io(ip_full_io),', '''.ip_full_io(ip_full_io),
    .result_valid(result_valid), .result_data(result_data), .result_ready(result_ready),'''),
        ('.wb_cyc_i   (wbs_cyc_i)', '.wb_cyc_i   (selected && wbs_we_i)'),
        ('.wb_ack_o   (wbs_ack_o)', '.wb_ack_o   (write_ack)'),
        ('output reg  [31:0] DO,', '''output reg  [31:0] DO,
    input wire result_ready,
    output wire result_valid,
    output wire [31:0] result_data,'''),
        ('wire op_full  =', '''assign result_valid = !op_empty;
  assign result_data = op_fifo[op_rptr_idx];
  wire op_full  ='''),
        ('else if (!EN) begin', 'if (result_ready) begin'),
        ('if (!ip_full) begin\n              // IP FIFO not full', 'if (!ip_full || !op_empty) begin\n              // Wait for all input words and room for the complete output batch'),
        ('wb_ack_o <= (wb_cyc_i && wb_stb_i && !wb_ack_o);',
         'wb_ack_o <= (wb_cyc_i && wb_stb_i && !wb_ack_o && !sram_full);'),
    ]
    patched = source
    # Declare the SRAM array before references (required by current Icarus).
    declaration = 'reg [DATA_WIDTH-1:0]    mem [0:RAM_DEPTH-1];'
    if patched.count(declaration) != 1 or patched.count('  reg  csb0_reg;') != 1:
        raise ValueError('Candidate SRAM declaration changed')
    patched = patched.replace(declaration, '').replace('  reg  csb0_reg;', declaration + '\n  reg  csb0_reg;')
    for old, new in replacements:
        if patched.count(old) != 1:
            raise ValueError('Candidate RTL changed: patch anchor is not unique: ' + old)
        patched = patched.replace(old, new, 1)
    # Keep the SRAM slot reserved until its word has been accepted. The upstream
    # rollback-on-full path lets a wrapped writer overwrite an outstanding read.
    start = patched.index('    // rd_pending:')
    end = patched.index('    // ============================================================\n    // SRAM Instance', start)
    patched = patched[:start] + '''    reg [1:0] read_state;
    reg [DATA_WIDTH-1:0] hold_data;
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            csb1 <= 1; addr1 <= 0; rptr <= 0;
            ext_wr_en <= 0; ext_dout <= 0;
            read_state <= 0; hold_data <= 0;
        end else begin
            csb1 <= 1;
            ext_wr_en <= 0;
            case (read_state)
                0: if (!sram_empty && !ext_full && !ext_wr_en) begin
                    csb1 <= 0; addr1 <= rptr; read_state <= 1;
                end
                1: read_state <= 2;
                2: begin hold_data <= dout1; read_state <= 3; end
                3: if (!ext_full) begin
                    ext_wr_en <= 1; ext_dout <= hold_data;
                    rptr <= rptr + 1'b1; read_state <= 0;
                end
            endcase
        end
    end

''' + patched[end:]
    return patched


def generate_testbench(out, patched=False):
    rng = random.Random(20261104)
    weights = [[rng.randrange(2) for _ in range(32)] for _ in range(32)]
    vectors = [[0]*32, [255]*32, [i*7 % 256 for i in range(32)]]
    vectors += [[rng.randrange(256) for _ in range(32)] for _ in range(5)]
    expected = [weights[r][c] for r in range(32) for c in range(32)]
    for vector in vectors:
        expected.extend((c << 20) | sum(vector[r]*weights[r][c] for r in range(32)) for c in range(32))
    write_json(out/'x2_vectors.json', {'weights': weights, 'inputs': vectors, 'expected': expected,
        'scope': 'Binary 32x32 weights, unsigned 8-bit inputs, P=0; source-derived candidate behavior only.'})
    header = '''`timescale 1ns/1ps
module x2_scoreboard_tb;
reg clk=0, rst=1;
always #10 clk=~clk;
reg cyc=0, stb=0, we=0;
reg [3:0] sel=0;
reg [31:0] addr=0, data=0;
wire [31:0] result;
wire ack;
integer checks=0, cycles=0, stalls=0;
reg [31:0] observed;
Neuromorphic_X2_wb #(.P(0)) dut(
 .user_clk(clk), .user_rst(rst), .wb_clk_i(clk), .wb_rst_i(rst),
 .wbs_stb_i(stb), .wbs_cyc_i(cyc), .wbs_we_i(we), .wbs_sel_i(sel),
 .wbs_dat_i(data), .wbs_adr_i(addr), .wbs_dat_o(result), .wbs_ack_o(ack),
 .ScanInCC(1'b0), .ScanInDL(1'b0), .ScanInDR(1'b0), .TM(1'b0),
 .Iref(1'b0), .Vcc_read(1'b0), .Vcomp(1'b0), .Bias_comp2(1'b0),
 .Vcc_wl_read(1'b0), .Vcc_wl_set(1'b0), .Vbias(1'b0), .Vcc_wl_reset(1'b0),
 .Vcc_set(1'b0), .Vcc_reset(1'b0), .Vcc_L(1'b0), .Vcc_Body(1'b0));
task transaction(input bit writing, input [31:0] word, output [31:0] value);
begin
 @(negedge clk); cyc=1; stb=1; we=writing; sel=15; addr=32'h3000000c; data=word;
 cycles=0;
 begin: awaiting_ack
  forever begin
   @(posedge clk);
   if(ack===1'b1) begin value=result; disable awaiting_ack; end
   cycles=cycles+1; stalls=stalls+1;
   if(cycles>100000) $fatal(1,"X2_ACK_TIMEOUT write=%b",writing);
  end
 end
 @(negedge clk); cyc=0; stb=0; we=0; sel=0; addr=0; data=0;
end
endtask
task check_result(input [31:0] expected);
begin
 transaction(0,0,observed);
 if(observed !== expected) $fatal(1,"X2_MISMATCH check=%d expected=%h actual=%h",checks,expected,observed);
 checks=checks+1;
end
endtask
initial begin
 repeat(5) @(negedge clk); rst=0;
 // Wrong addresses and incomplete byte enables must never acknowledge.
 @(negedge clk); cyc=1; stb=1; we=1; sel=15; addr=32'h30000010;
 repeat(4) begin @(posedge clk); #1; if(ack!==0) $fatal(1,"X2_ADDRESS_DECODE"); end
 @(negedge clk); addr=32'h3000000c; sel=1;
 repeat(4) begin @(posedge clk); #1; if(ack!==0) $fatal(1,"X2_BYTE_SELECT"); end
 @(negedge clk); cyc=0; stb=0; we=0; sel=0;
'''
    lines = [header]
    for r in range(32):
        for c in range(32):
            word = (3 << 30) | (r << 25) | (c << 20) | (255 if weights[r][c] else 0)
            lines.append(f"transaction(1,32'h{word:08x},observed);")
    # Read each written bit with an independently predicted expected value.
    for r in range(32):
        for c in range(32):
            word = (1 << 30) | (r << 25) | (c << 20)
            lines.extend([f"transaction(1,32'h{word:08x},observed);", f"check_result(32'd{weights[r][c]});"])
    # Queue two batches before draining either: the second must wait for output
    # space instead of overwriting the first full result FIFO.
    for pair in range(0, len(vectors), 2):
        for vector in vectors[pair:pair+2]:
            for r, value in enumerate(vector):
                word = (2 << 30) | (r << 25) | value
                lines.append(f"transaction(1,32'h{word:08x},observed);")
        lines.append(f'repeat({120 + pair*7}) @(negedge clk);')
        for vector in vectors[pair:pair+2]:
            for c in range(32):
                value = (c << 20) | sum(vector[r]*weights[r][c] for r in range(32))
                lines.append(f"check_result(32'h{value:08x});")
    lines += ['@(negedge clk); rst=1; repeat(5) @(negedge clk); rst=0;',
        'repeat(3) @(negedge clk);', 'if(ack!==0) $fatal(1,"X2_RESET_ACK");',
        f'$display("BMLABS_X2_PASS checks={len(expected)} vectors={len(vectors)} stalls=%0d",stalls);',
        '$finish; end', 'initial begin #100000000; $fatal(1,"X2_GLOBAL_TIMEOUT"); end', 'endmodule']
    (out/'x2_scoreboard_tb.v').write_text('\n'.join(lines), encoding='utf-8')
    return {'checks': len(expected), 'vectors': len(vectors), 'seed': 20261104,
        'coverage': ['write/read 1024 cells', '8 matrix-vector batches', 'read stalls and queued batch output backpressure', 'input FIFO/SRAM wraps', 'address/byte-select rejection', 'idle reset'],
        'not_covered': ['reset during busy operation', 'P>0 feedback', 'analog behavior', 'CDC', 'configured FABulous fabric']}


def prepare(out, patched):
    root = Path(settings.COMPILER_X1_REPO)
    source = root/'Neuromorphic_X2_32x32_updating_SRAM/Neuromorphic_X2_with_SRAM/Neuromorphic_X2_Beh.v'
    data = source.read_bytes()
    original = data.decode('utf-8-sig').replace('\r\n', '\n')
    selected = candidate_patch(original) if patched else original
    (out/'x2_source.v').write_text(selected, encoding='utf-8')
    if patched:
        (out/'x2_candidate.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True), selected.splitlines(True),
            fromfile='upstream/Neuromorphic_X2_Beh.v', tofile='candidate/Neuromorphic_X2_Beh.v')), encoding='utf-8')
    plan = generate_testbench(out, patched)
    plan.update(source_path=str(source), source_sha256=hashlib.sha256(data).hexdigest(),
        candidate_sha256=hashlib.sha256(selected.encode()).hexdigest(), patched=patched,
        contract_status='candidate contract; not a finalized X2 ABI')
    write_json(out/'x2_plan.json', plan)
    return plan


def run(out, command, patched=True):
    plan = prepare(out, patched)
    command('x2_compile', tool_command('IVERILOG',
        ['-g2012', '-Wall', '-s', 'x2_scoreboard_tb', '-o', 'x2.vvp', 'x2_source.v', 'x2_scoreboard_tb.v'], out), 90)
    result = command('x2_scoreboard', tool_command('VVP', ['-n', 'x2.vvp'], out, timeout=120), 150)
    marker = f"BMLABS_X2_PASS checks={plan['checks']} vectors={plan['vectors']} stalls="
    if not any(line.startswith(marker) for line in result['stdout'].splitlines()):
        raise ValueError('X2 scoreboard did not report completion')
    return {'status': 'passed', **plan}
