// rgb_in.v  -- parallel-RGB (DPI) input front-end.
//
// The canonical FPGA input for the prototype: a generic parallel video bus
// driven by a commodity bridge chip (Lontium LT-series / TI TFP401 / etc.) that
// receives HDMI/DVI/DP and outputs pixel clock + DE/HSync/VSync + 24-bit RGB,
// with the proprietary standard (and any license) sealed inside the chip. The
// FPGA just samples the bus in the pixel-clock domain -- no transceivers, no
// decode logic, no licensed IP in the bitstream.
//
// On hardware `in_*` come from the bridge pins (optionally via IO/IDDR input
// registers). Here it is a simple registration stage so the pixel stream is
// cleanly clocked before the compositor. Swap the bridge to change input
// standard; this module and everything downstream is unchanged.

`default_nettype none

module rgb_in (
    input  wire        clk,        // pixel clock (from bridge)
    // raw parallel bus from the bridge chip
    input  wire        in_de,
    input  wire        in_hsync,
    input  wire        in_vsync,
    input  wire [7:0]  in_r,
    input  wire [7:0]  in_g,
    input  wire [7:0]  in_b,
    // registered pixel stream (pixel-clock domain)
    output reg         de,
    output reg         hsync,
    output reg         vsync,
    output reg [7:0]   r,
    output reg [7:0]   g,
    output reg [7:0]   b
);
    always @(posedge clk) begin
        de    <= in_de;
        hsync <= in_hsync;
        vsync <= in_vsync;
        r     <= in_r;
        g     <= in_g;
        b     <= in_b;
    end
endmodule

`default_nettype wire
