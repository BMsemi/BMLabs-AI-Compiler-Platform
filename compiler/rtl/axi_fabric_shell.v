// BM Labs experimental ZCU106/FABulous shell, ABI v1. Not the final ASIC ABI.
// 00 magic BMF1; 04 version; 08 resetn (bit0); 0c config data FIFO;
// 10 words accepted; 14 one-clock user command; 18 user result; 1c direction.
module axi_fabric_shell(
 (* X_INTERFACE_INFO="xilinx.com:signal:clock:1.0 aclk CLK", X_INTERFACE_PARAMETER="ASSOCIATED_BUSIF S_AXI, ASSOCIATED_RESET aresetn" *) input wire aclk,
 (* X_INTERFACE_INFO="xilinx.com:signal:reset:1.0 aresetn RST", X_INTERFACE_PARAMETER="POLARITY ACTIVE_LOW" *) input wire aresetn,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI AWADDR" *) input wire [7:0] s_axi_awaddr,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI AWPROT" *) input wire [2:0] s_axi_awprot,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI AWVALID" *) input wire s_axi_awvalid,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI AWREADY" *) output wire s_axi_awready,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WDATA" *) input wire [31:0] s_axi_wdata,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WSTRB" *) input wire [3:0] s_axi_wstrb,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WVALID" *) input wire s_axi_wvalid,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WREADY" *) output wire s_axi_wready,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI BRESP" *) output reg [1:0] s_axi_bresp,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI BVALID" *) output reg s_axi_bvalid,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI BREADY" *) input wire s_axi_bready,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI ARADDR" *) input wire [7:0] s_axi_araddr,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI ARPROT" *) input wire [2:0] s_axi_arprot,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI ARVALID" *) input wire s_axi_arvalid,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI ARREADY" *) output wire s_axi_arready,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RDATA" *) output reg [31:0] s_axi_rdata,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RRESP" *) output reg [1:0] s_axi_rresp,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RVALID" *) output reg s_axi_rvalid,
 (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RREADY" *) input wire s_axi_rready
);
reg aw_held,w_held;
reg [7:0] address;
reg [31:0] data;
reg [3:0] strobes;
reg fabric_resetn;
reg [31:0] config_data,word_count;
reg config_strobe;
reg [2:0] config_state;
reg [15:0] user_command;
wire [15:0] user_result,user_direction;
wire active,receive_led;
assign s_axi_awready=!aw_held && !s_axi_bvalid && config_state==0;
assign s_axi_wready=!w_held && !s_axi_bvalid && config_state==0;
assign s_axi_arready=!s_axi_rvalid;
eFPGA_top fabric(.CLK(aclk),.resetn(fabric_resetn),.SelfWriteData(config_data),
 .SelfWriteStrobe(config_strobe),.O_top(user_command),.I_top(user_result),.T_top(user_direction),
 .Rx(1'b1),.s_clk(1'b0),.s_data(1'b0),.ComActive(active),.ReceiveLED(receive_led),
 .A_config_C(),.B_config_C(),.Config_accessC());
always @(posedge aclk) begin
 if(!aresetn) begin
  aw_held<=0;w_held<=0;address<=0;data<=0;strobes<=0;
  s_axi_bvalid<=0;s_axi_bresp<=0;s_axi_rvalid<=0;s_axi_rdata<=0;s_axi_rresp<=0;
  fabric_resetn<=0;config_data<=0;config_strobe<=0;config_state<=0;word_count<=0;user_command<=0;
 end else begin
  user_command<=0;
  if(s_axi_bvalid && s_axi_bready) s_axi_bvalid<=0;
  if(s_axi_rvalid && s_axi_rready) s_axi_rvalid<=0;
  if(s_axi_awvalid && s_axi_awready) begin aw_held<=1;address<=s_axi_awaddr;end
  if(s_axi_wvalid && s_axi_wready) begin w_held<=1;data<=s_axi_wdata;strobes<=s_axi_wstrb;end
  if(aw_held && w_held && !s_axi_bvalid && config_state==0) begin
   aw_held<=0;w_held<=0;s_axi_bresp<=0;s_axi_bvalid<=1;
   if(strobes!=4'b1111 || address[1:0]!=0) s_axi_bresp<=2'b10;
   else case(address)
    8'h08: begin fabric_resetn<=data[0];if(!data[0])word_count<=0;end
    8'h0c: if(!fabric_resetn || word_count>=4096) s_axi_bresp<=2'b10;
            else begin config_data<=data;config_state<=1;s_axi_bvalid<=0;end
    8'h14: if(!fabric_resetn) s_axi_bresp<=2'b10; else user_command<=data[15:0];
    default:s_axi_bresp<=2'b10;
   endcase
  end
  case(config_state)
   1:config_state<=2;
   2:begin config_strobe<=1;config_state<=3;end
   3:begin config_strobe<=0;config_state<=4;end
   4:config_state<=5;
   5:begin config_state<=0;word_count<=word_count+1;s_axi_bvalid<=1;s_axi_bresp<=0;end
   default:begin end
  endcase
  if(s_axi_arvalid && s_axi_arready) begin
   s_axi_rvalid<=1;s_axi_rresp<=0;
   case(s_axi_araddr)
    8'h00:s_axi_rdata<=32'h424d4631;
    8'h04:s_axi_rdata<=32'h00010000;
    8'h08:s_axi_rdata<={29'd0,receive_led,active,fabric_resetn};
    8'h10:s_axi_rdata<=word_count;
    8'h18:s_axi_rdata<={16'd0,user_result};
    8'h1c:s_axi_rdata<={16'd0,user_direction};
    default:begin s_axi_rdata<=0;s_axi_rresp<=2'b10;end
   endcase
  end
 end
end
endmodule
