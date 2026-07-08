// pwm.v  -- simple backlight PWM generator.
//
// Free-running BITS-bit counter; output is high while counter < duty, so duty
// 0..(2^BITS-1) maps to 0..~100% brightness. duty = all-ones is forced fully on
// (so the full range reaches true 100%). PWM frequency = clk / 2^BITS; widen
// BITS (or add a prescaler) to lower it for a given driver.
//
// Drives a CCFL inverter's dimming input or an LED-driver PWM/EN pin.

`default_nettype none

module pwm #(
    parameter BITS = 8
)(
    input  wire            clk,
    input  wire            rst,
    input  wire [BITS-1:0] duty,
    output reg             pwm
);
    reg [BITS-1:0] cnt;

    always @(posedge clk) begin
        if (rst) begin
            cnt <= {BITS{1'b0}};
            pwm <= 1'b0;
        end else begin
            cnt <= cnt + 1'b1;
            pwm <= (duty == {BITS{1'b1}}) ? 1'b1 : (cnt < duty);
        end
    end
endmodule

`default_nettype wire
