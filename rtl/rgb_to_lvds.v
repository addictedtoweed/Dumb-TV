// rgb_to_lvds.v -- parallel RGB -> FPD-Link (LVDS) logical mapper.
//
// The LOGICAL half of a native-LVDS output: it takes the compositor's parallel
// RGB + sync and assembles the 7-bit-per-lane words a 7:1 FPD-Link serializer
// (OSERDES) clocks out -- 4 data lanes (D0..D3) + a clock lane. The high-speed
// serialization and the true-differential I/O are device primitives dropped in
// on top (per FPGA, at synthesis); this module is what makes one bitstream fit
// many panels, and it is fully simulatable.
//
// Runtime config (so people rewire their harness to a fixed FPGA connector and
// then adapt in software):
//   * cfg_bpp24  -- 24bpp (uses D3) vs 18bpp (D3 idle)
//   * cfg_jeida  -- JEIDA vs VESA/SPWG bit packing (which 6 of 8 bits ride the
//                   main lanes; the other 2 ride D3)
//   * cfg_*_pol  -- invert any data lane / the clock lane / DE/HS/VS
//                   (swapping a differential pair in the harness == a pol flip)
//
// LVDS/FPD-Link is an open electrical standard (no licensed IP), so driving it
// straight from the FPGA keeps the bitstream clean -- unlike the HDMI/DP input,
// which is why that side uses a bridge chip.
//
// Single-link (1 px / clock) here; dual-link (2 px / clock for 1080p60) is the
// same mapper instantiated twice on an odd/even pixel pair -- a follow-on that
// needs a 2px-wide pipeline.
//
// NOTE: the exact VESA/JEIDA bit significance and the clock-lane pattern should
// be confirmed against the target panel's datasheet at bring-up; they're config
// here precisely so that's a settings change, not a re-synthesis.

`default_nettype none

module rgb_to_lvds #(
    parameter [6:0] CLK_PATTERN = 7'b1100011   // clock-lane 7:1 word (adjust to panel)
)(
    input  wire       clk,               // pixel clock
    input  wire       rst,
    // parallel video (from the compositor)
    input  wire       de, hs, vs,
    input  wire [7:0] r, g, b,
    // runtime config
    input  wire       cfg_bpp24,         // 1 = 24bpp (D3 used), 0 = 18bpp
    input  wire       cfg_jeida,         // 1 = JEIDA packing, 0 = VESA/SPWG
    input  wire [3:0] cfg_data_pol,      // invert data lanes D0..D3
    input  wire       cfg_clk_pol,       // invert clock lane
    input  wire       cfg_de_pol,
    input  wire       cfg_hs_pol,
    input  wire       cfg_vs_pol,
    // 7-bit-per-lane words to the 7:1 serializers (one word per pixel clock)
    output reg  [6:0] d0, d1, d2, d3,
    output reg  [6:0] clk_lane,
    output reg        word_en
);
    // Pick the 6 "core" bits (main lanes) and 2 "extra" bits (D3) per colour.
    // VESA: core = bits[5:0], extra = bits[7:6].  JEIDA: core = [7:2], extra = [1:0].
    wire [5:0] rc = cfg_jeida ? r[7:2] : r[5:0];
    wire [1:0] rx = cfg_jeida ? r[1:0] : r[7:6];
    wire [5:0] gc = cfg_jeida ? g[7:2] : g[5:0];
    wire [1:0] gx = cfg_jeida ? g[1:0] : g[7:6];
    wire [5:0] bc = cfg_jeida ? b[7:2] : b[5:0];
    wire [1:0] bx = cfg_jeida ? b[1:0] : b[7:6];

    wire sde = de ^ cfg_de_pol;
    wire shs = hs ^ cfg_hs_pol;
    wire svs = vs ^ cfg_vs_pol;

    // FPD-Link 7:1 slot assignment (bit 0 = first serialized out).
    wire [6:0] w0 = {gc[0], rc};                       // R0..R5, G0
    wire [6:0] w1 = {bc[1], bc[0], gc[5:1]};           // G1..G5, B0, B1
    wire [6:0] w2 = {sde, svs, shs, bc[5:2]};          // B2..B5, HS, VS, DE
    wire [6:0] w3 = cfg_bpp24 ?                         // extra 2 bits/colour
                    {rx[1], rx[0], gx[1], gx[0], bx[1], bx[0], 1'b0} : 7'd0;

    always @(posedge clk) begin
        if (rst) begin
            d0 <= 7'd0; d1 <= 7'd0; d2 <= 7'd0; d3 <= 7'd0;
            clk_lane <= 7'd0; word_en <= 1'b0;
        end else begin
            d0 <= w0 ^ {7{cfg_data_pol[0]}};           // pair-polarity = XOR the word
            d1 <= w1 ^ {7{cfg_data_pol[1]}};
            d2 <= w2 ^ {7{cfg_data_pol[2]}};
            d3 <= w3 ^ {7{cfg_data_pol[3]}};
            clk_lane <= CLK_PATTERN ^ {7{cfg_clk_pol}};
            word_en <= 1'b1;
        end
    end
endmodule

`default_nettype wire
