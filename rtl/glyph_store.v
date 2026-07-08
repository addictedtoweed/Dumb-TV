// glyph_store.v  -- block-RAM bank of reusable OSD glyphs.
//
// Holds N_GLYPHS glyphs, each GW x GH pixels of 4-bit palette index (index 0 =
// transparent). Uploaded once by GLYPH_UPLOAD and blitted many times, so a HUD
// (text, arrows, icons) costs almost no serial bandwidth. Single clock (the
// UART/system domain, where the blit engine runs). 1-clock synchronous read.

`default_nettype none

module glyph_store #(
    parameter N_GLYPHS = 8,
    parameter GW       = 4,
    parameter GH       = 4,
    parameter GPIX     = GW * GH,
    parameter GAW      = $clog2(N_GLYPHS * GPIX)
)(
    input  wire           clk,
    input  wire           we,
    input  wire [GAW-1:0] waddr,
    input  wire [3:0]     wdata,
    input  wire [GAW-1:0] raddr,
    output reg  [3:0]     rdata
);
    reg [3:0] mem [0:(N_GLYPHS*GPIX)-1];

    always @(posedge clk) begin
        if (we) mem[waddr] <= wdata;
        rdata <= mem[raddr];
    end
endmodule

`default_nettype wire
