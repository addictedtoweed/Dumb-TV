// ctrl_regs.v
//
// The control plane registers. Written by the UART command parser (or cocotb).
// The OSD is now full-screen (the canvas stretches to the whole active area),
// so there is no window position/size -- just an enable and a master fade.

`default_nettype none

module ctrl_regs (
    input  wire        clk,
    input  wire        rst,
    input  wire [3:0]  addr,
    input  wire [15:0] wdata,
    input  wire        we,
    output reg         osd_enable,
    output reg [7:0]   osd_alpha,   // master fade: 0 = OSD off, 255 = full
    output reg [3:0]   mux_sel      // input mux select (INPUT_SELECT command)
);
    localparam A_ENABLE = 4'd0;
    localparam A_ALPHA  = 4'd1;
    localparam A_MUX    = 4'd2;

    always @(posedge clk) begin
        if (rst) begin
            osd_enable <= 1'b0;
            osd_alpha  <= 8'd0;
            mux_sel    <= 4'd0;
        end else if (we) begin
            case (addr)
                A_ENABLE: osd_enable <= wdata[0];
                A_ALPHA:  osd_alpha  <= wdata[7:0];
                A_MUX:    mux_sel    <= wdata[3:0];
                default:  ; // no-op
            endcase
        end
    end
endmodule

`default_nettype wire
