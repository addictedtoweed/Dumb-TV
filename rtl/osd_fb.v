// osd_fb.v
//
// The OSD framebuffer: a small block-RAM holding the overlay image at low
// resolution. Each entry is packed {alpha, R, G, B} = 32 bits.
//
//   bits [31:24] = alpha (per-pixel)
//   bits [23:16] = R
//   bits [15:8]  = G
//   bits [7:0]   = B
//
// One write port (loaded by the host / CPU; in sim by cocotb) and one
// synchronous read port (1-clock latency -- the compositor pipelines around
// it). OSD_W and OSD_H must be powers of two so the read address is just a
// concatenation of the within-OSD coordinates.

`default_nettype none

module osd_fb #(
    parameter OSD_W = 8,
    parameter OSD_H = 4,
    parameter AW    = $clog2(OSD_W*OSD_H)
)(
    input  wire           clk,
    // write port
    input  wire           we,
    input  wire [AW-1:0]  waddr,
    input  wire [31:0]    wdata,
    // read port (synchronous, +1 clk)
    input  wire [AW-1:0]  raddr,
    output reg  [31:0]    rdata
);
    reg [31:0] mem [0:(OSD_W*OSD_H)-1];

    always @(posedge clk) begin
        if (we) mem[waddr] <= wdata;
        rdata <= mem[raddr];
    end
endmodule

`default_nettype wire
