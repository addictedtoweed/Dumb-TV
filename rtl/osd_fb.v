// osd_fb.v
//
// The OSD framebuffer: a small dual-clock block-RAM holding the overlay image
// at low resolution. Each entry is packed {alpha, R, G, B} = 32 bits.
//
//   bits [31:24] = alpha (per-pixel)
//   bits [23:16] = R
//   bits [15:8]  = G
//   bits [7:0]   = B
//
// DUAL CLOCK: the write port runs on the host/UART clock (wr_clk); the read
// port runs on the pixel clock (rd_clk). This is the natural block-RAM CDC for
// the real product, where the pixel clock arrives from the RGB-input bridge
// (e.g. a Lontium/TFP401 HDMI->RGB chip) and the control plane runs on a
// separate system clock. Tie wr_clk = rd_clk for single-clock use.
//
// OSD_W and OSD_H must be powers of two so the read address is just a
// concatenation of the within-OSD coordinates.

`default_nettype none

module osd_fb #(
    parameter OSD_W = 8,
    parameter OSD_H = 4,
    parameter AW    = $clog2(OSD_W*OSD_H)
)(
    // write port (system / UART clock domain)
    input  wire           wr_clk,
    input  wire           we,
    input  wire [AW-1:0]  waddr,
    input  wire [31:0]    wdata,
    // read port (pixel clock domain, synchronous +1 clk)
    input  wire           rd_clk,
    input  wire [AW-1:0]  raddr,
    output reg  [31:0]    rdata
);
    reg [31:0] mem [0:(OSD_W*OSD_H)-1];

    always @(posedge wr_clk)
        if (we) mem[waddr] <= wdata;

    always @(posedge rd_clk)
        rdata <= mem[raddr];
endmodule

`default_nettype wire
