// video_timing.v
//
// Generates a raster scan: de (data enable), hsync, vsync and the current
// (x,y) coordinate. In the real product this block is REPLACED by the
// DisplayPort RX IP, which recovers exactly these signals from the link.
// Keeping it here lets the whole pipeline free-run in simulation and also
// gives you a synthesizable on-board test-pattern source for bring-up.
//
// Defaults are deliberately tiny (16x8 active) so cocotb tests run fast.
// For 1080p, override the parameters (see README) -- the logic is identical.

`default_nettype none

module video_timing #(
    parameter CW       = 12,   // coordinate width (12 bits covers 1920/1080)
    parameter H_ACTIVE = 16, H_FP = 2, H_SYNC = 2, H_BP = 2,
    parameter V_ACTIVE = 8,  V_FP = 1, V_SYNC = 1, V_BP = 1
)(
    input  wire           clk,
    input  wire           rst,
    output wire           hsync,
    output wire           vsync,
    output wire           de,
    output wire [CW-1:0]  x,
    output wire [CW-1:0]  y
);
    localparam H_TOTAL = H_ACTIVE + H_FP + H_SYNC + H_BP;
    localparam V_TOTAL = V_ACTIVE + V_FP + V_SYNC + V_BP;

    reg [CW-1:0] hc, vc;

    always @(posedge clk) begin
        if (rst) begin
            hc <= {CW{1'b0}};
            vc <= {CW{1'b0}};
        end else if (hc == H_TOTAL-1) begin
            hc <= {CW{1'b0}};
            vc <= (vc == V_TOTAL-1) ? {CW{1'b0}} : vc + 1'b1;
        end else begin
            hc <= hc + 1'b1;
        end
    end

    wire h_active = (hc < H_ACTIVE);
    wire v_active = (vc < V_ACTIVE);

    // Combinational so (x,y) line up in the same cycle as de/rgb downstream.
    assign de    = h_active && v_active;
    assign hsync = (hc >= H_ACTIVE+H_FP) && (hc < H_ACTIVE+H_FP+H_SYNC);
    assign vsync = (vc >= V_ACTIVE+V_FP) && (vc < V_ACTIVE+V_FP+V_SYNC);
    assign x     = hc;
    assign y     = vc;
endmodule

`default_nettype wire
