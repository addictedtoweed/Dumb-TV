// uart_rx.v  -- 8N1 UART receiver.
//
// Oversamples the RX line: detects the start bit, samples each data bit at its
// center (LSB first), and strobes `valid` for one clock when a byte is ready.
// CLKS_PER_BIT = clk frequency / baud rate (use a small value in simulation).

`default_nettype none

module uart_rx #(
    parameter CLKS_PER_BIT = 8
)(
    input  wire       clk,
    input  wire       rst,
    input  wire       rx,
    output reg  [7:0] data,
    output reg        valid
);
    localparam IDLE = 2'd0, START = 2'd1, DATA = 2'd2, STOP = 2'd3;

    reg [1:0]  state;
    reg [15:0] clk_cnt;
    reg [2:0]  bit_idx;
    reg        rx_d, rx_q;     // 2-flop synchronizer

    always @(posedge clk) begin
        if (rst) begin rx_d <= 1'b1; rx_q <= 1'b1; end
        else     begin rx_d <= rx;  rx_q <= rx_d; end
    end

    always @(posedge clk) begin
        if (rst) begin
            state   <= IDLE;
            valid   <= 1'b0;
            clk_cnt <= 16'd0;
            bit_idx <= 3'd0;
            data    <= 8'd0;
        end else begin
            valid <= 1'b0;
            case (state)
                IDLE: begin
                    clk_cnt <= 16'd0;
                    bit_idx <= 3'd0;
                    if (~rx_q) state <= START;     // start bit (line low)
                end
                START: begin
                    if (clk_cnt == (CLKS_PER_BIT-1)/2) begin
                        if (~rx_q) begin clk_cnt <= 16'd0; state <= DATA; end
                        else        state <= IDLE; // false start
                    end else clk_cnt <= clk_cnt + 1'b1;
                end
                DATA: begin
                    if (clk_cnt == CLKS_PER_BIT-1) begin
                        clk_cnt        <= 16'd0;
                        data[bit_idx]  <= rx_q;     // LSB first
                        if (bit_idx == 3'd7) begin bit_idx <= 3'd0; state <= STOP; end
                        else                       bit_idx <= bit_idx + 1'b1;
                    end else clk_cnt <= clk_cnt + 1'b1;
                end
                STOP: begin
                    if (clk_cnt == CLKS_PER_BIT-1) begin
                        valid <= 1'b1;
                        state <= IDLE;
                    end else clk_cnt <= clk_cnt + 1'b1;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
