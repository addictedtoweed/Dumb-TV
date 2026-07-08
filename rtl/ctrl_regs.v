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
    output reg [3:0]   mux_sel,     // input mux select (INPUT_SELECT command)
    output reg [7:0]   brightness,  // picture brightness (128 = neutral)
    output reg [7:0]   contrast,    // picture contrast   (128 = unity gain)
    output reg [7:0]   backlight,   // backlight PWM duty (255 = full on)
    output reg         core_halt    // SERV core reset (1 = held; FW_HALT/START)
);
    localparam A_ENABLE = 4'd0;
    localparam A_ALPHA  = 4'd1;
    localparam A_MUX    = 4'd2;
    localparam A_BRIGHT = 4'd3;
    localparam A_CONTR  = 4'd4;
    localparam A_BL     = 4'd5;
    localparam A_CORE   = 4'd6;

    always @(posedge clk) begin
        if (rst) begin
            osd_enable <= 1'b0;
            osd_alpha  <= 8'd0;
            mux_sel    <= 4'd0;
            brightness <= 8'd128;    // neutral
            contrast   <= 8'd128;    // unity
            backlight  <= 8'd255;    // full on (visible out of the box)
            core_halt  <= 1'b1;      // core held until firmware is loaded + FW_START
        end else if (we) begin
            case (addr)
                A_ENABLE: osd_enable <= wdata[0];
                A_ALPHA:  osd_alpha  <= wdata[7:0];
                A_MUX:    mux_sel    <= wdata[3:0];
                A_BRIGHT: brightness <= wdata[7:0];
                A_CONTR:  contrast   <= wdata[7:0];
                A_BL:     backlight  <= wdata[7:0];
                A_CORE:   core_halt  <= wdata[0];
                default:  ; // no-op
            endcase
        end
    end
endmodule

`default_nettype wire
