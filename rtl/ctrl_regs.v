// ctrl_regs.v
//
// The control plane. A trivial write-only register file. In the product this
// is driven by the UART command parser (the Pi / Linux host's serial link);
// in simulation cocotb writes it directly. Same register map either way --
// that's the point: the OSD/picture controls live here, host-agnostic.
//
// OSD pixel color now comes from the framebuffer (osd_fb), so the old per-
// register R/G/B are gone; osd_alpha is now a MASTER fade over the
// framebuffer's per-pixel alpha.

`default_nettype none

module ctrl_regs (
    input  wire        clk,
    input  wire        rst,
    input  wire [3:0]  addr,
    input  wire [15:0] wdata,
    input  wire        we,
    // OSD configuration outputs
    output reg         osd_enable,
    output reg [15:0]  osd_x0,
    output reg [15:0]  osd_y0,
    output reg [15:0]  osd_w,
    output reg [15:0]  osd_h,
    output reg [7:0]   osd_alpha    // master fade: 0 = OSD off, 255 = full
);
    // Register map
    localparam A_ENABLE = 4'd0;
    localparam A_X0     = 4'd1;
    localparam A_Y0     = 4'd2;
    localparam A_W      = 4'd3;
    localparam A_H      = 4'd4;
    localparam A_ALPHA  = 4'd5;

    always @(posedge clk) begin
        if (rst) begin
            osd_enable <= 1'b0;
            osd_x0     <= 16'd0;
            osd_y0     <= 16'd0;
            osd_w      <= 16'd0;
            osd_h      <= 16'd0;
            osd_alpha  <= 8'd0;
        end else if (we) begin
            case (addr)
                A_ENABLE: osd_enable <= wdata[0];
                A_X0:     osd_x0     <= wdata;
                A_Y0:     osd_y0     <= wdata;
                A_W:      osd_w      <= wdata;
                A_H:      osd_h      <= wdata;
                A_ALPHA:  osd_alpha  <= wdata[7:0];
                default:  ; // no-op
            endcase
        end
    end
endmodule

`default_nettype wire
