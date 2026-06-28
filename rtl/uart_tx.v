// uart_tx.v  -- 8N1 UART transmitter.
//
// Assert `start` for one clock with `data` valid while `busy` is low; the byte
// is shifted out LSB first. `busy` stays high until the stop bit completes.

`default_nettype none

module uart_tx #(
    parameter CLKS_PER_BIT = 8
)(
    input  wire       clk,
    input  wire       rst,
    input  wire [7:0] data,
    input  wire       start,
    output reg        tx,
    output reg        busy
);
    localparam IDLE = 2'd0, START = 2'd1, DATA = 2'd2, STOP = 2'd3;

    reg [1:0]  state;
    reg [15:0] clk_cnt;
    reg [2:0]  bit_idx;
    reg [7:0]  shreg;

    always @(posedge clk) begin
        if (rst) begin
            state   <= IDLE;
            tx      <= 1'b1;
            busy    <= 1'b0;
            clk_cnt <= 16'd0;
            bit_idx <= 3'd0;
            shreg   <= 8'd0;
        end else begin
            case (state)
                IDLE: begin
                    tx      <= 1'b1;
                    busy    <= 1'b0;
                    clk_cnt <= 16'd0;
                    bit_idx <= 3'd0;
                    if (start) begin
                        shreg <= data;
                        busy  <= 1'b1;
                        state <= START;
                    end
                end
                START: begin
                    busy <= 1'b1;
                    tx   <= 1'b0;                    // start bit
                    if (clk_cnt == CLKS_PER_BIT-1) begin clk_cnt <= 16'd0; state <= DATA; end
                    else clk_cnt <= clk_cnt + 1'b1;
                end
                DATA: begin
                    busy <= 1'b1;
                    tx   <= shreg[bit_idx];          // LSB first
                    if (clk_cnt == CLKS_PER_BIT-1) begin
                        clk_cnt <= 16'd0;
                        if (bit_idx == 3'd7) begin bit_idx <= 3'd0; state <= STOP; end
                        else                       bit_idx <= bit_idx + 1'b1;
                    end else clk_cnt <= clk_cnt + 1'b1;
                end
                STOP: begin
                    busy <= 1'b1;
                    tx   <= 1'b1;                    // stop bit
                    if (clk_cnt == CLKS_PER_BIT-1) begin
                        clk_cnt <= 16'd0;
                        busy    <= 1'b0;
                        state   <= IDLE;
                    end else clk_cnt <= clk_cnt + 1'b1;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
