// serv_soc.v  -- SERV RISC-V SoC for Dumb-TV.
//
// A trimmed Servant SoC (see rtl/serv/servant.v, vendored) with two changes:
//   * program RAM is the host-writable serv_ram_hw (firmware uploaded over
//     FW_WRITE) instead of a $readmemh-baked servant_ram;
//   * the core is gated by core_halt (FW_HALT/FW_START) so firmware loads while
//     the core is held in reset, then runs when released.
//
// The core's GPIO `q` is the firmware's bit-banged UART TX -- routed to the
// internal command link (cmd_mux source 1) at the top level. Debug taps expose
// the instruction-bus so a test can watch the core fetch/advance.
//
// Uses the vendored SERV (ISC) + Servile (Apache-2.0) modules under rtl/serv/.

`default_nettype none

module serv_soc #(
    parameter MEMSIZE = 16384,
    parameter AW      = $clog2(MEMSIZE)
)(
    input  wire        clk,
    input  wire        rst,
    input  wire        core_halt,       // 1 = hold core in reset (loading fw)
    // host firmware write port
    input  wire        i_host_we,
    input  wire [AW-1:0] i_host_adr,
    input  wire [7:0]  i_host_dat,
    // consumer-IR receiver input (e.g. TSOP38238, idle high, active low). The
    // firmware reads it at the GPIO address (bit 0) to learn/decode remotes.
    input  wire        ir_in,
    // firmware-bit-banged UART TX (to the internal command link)
    output wire        q,
    // debug taps
    output wire [31:0] dbg_mem_adr,
    output wire        dbg_mem_stb
);
    localparam with_csr  = 1;
    localparam width     = 1;
    localparam rf_width  = width * 2;
    localparam csr_regs  = with_csr * 4;
    localparam rf_l2d    = $clog2((32 + csr_regs) * 32 / rf_width);

    wire core_rst = rst | core_halt;

    wire        timer_irq;

    wire [31:0] wb_mem_adr, wb_mem_dat, wb_mem_rdt;
    wire [3:0]  wb_mem_sel;
    wire        wb_mem_we, wb_mem_stb, wb_mem_ack;

    wire        wb_gpio_dat, wb_gpio_we, wb_gpio_stb, wb_gpio_rdt;
    wire [31:0] wb_timer_dat, wb_timer_rdt;
    wire        wb_timer_we, wb_timer_stb;

    wire [31:0] wb_ext_adr, wb_ext_dat, wb_ext_rdt;
    wire [3:0]  wb_ext_sel;
    wire        wb_ext_we, wb_ext_stb, wb_ext_ack;

    wire [rf_l2d-1:0]   rf_waddr, rf_raddr;
    wire [rf_width-1:0] rf_wdata, rf_rdata;
    wire                rf_wen, rf_ren;

    assign dbg_mem_adr = wb_mem_adr;
    assign dbg_mem_stb = wb_mem_stb;

    // CDC-sync the async IR pin into the core clock domain. Reads of the GPIO
    // address return this (bit 0); writes still drive the TX pin q -- a
    // bidirectional GPIO (read = IR in, write = UART out). Idle high.
    reg [1:0] ir_ff;
    always @(posedge clk)
        ir_ff <= rst ? 2'b11 : {ir_ff[0], ir_in};
    wire ir_sync = ir_ff[1];

    servant_mux servant_mux (
        .i_clk (clk), .i_rst (core_rst),
        .i_wb_cpu_adr (wb_ext_adr), .i_wb_cpu_dat (wb_ext_dat),
        .i_wb_cpu_sel (wb_ext_sel), .i_wb_cpu_we (wb_ext_we),
        .i_wb_cpu_cyc (wb_ext_stb), .o_wb_cpu_rdt (wb_ext_rdt),
        .o_wb_cpu_ack (wb_ext_ack),
        .o_wb_gpio_dat (wb_gpio_dat), .o_wb_gpio_we (wb_gpio_we),
        .o_wb_gpio_cyc (wb_gpio_stb), .i_wb_gpio_rdt (ir_sync),
        .o_wb_timer_dat (wb_timer_dat), .o_wb_timer_we (wb_timer_we),
        .o_wb_timer_cyc (wb_timer_stb), .i_wb_timer_rdt (wb_timer_rdt));

    // host-writable program RAM (replaces servant_ram)
    serv_ram_hw #(.depth (MEMSIZE)) ram (
        .i_wb_clk (clk), .i_wb_rst (core_rst),
        .i_wb_adr (wb_mem_adr[AW-1:2]),
        .i_wb_cyc (wb_mem_stb), .i_wb_we (wb_mem_we),
        .i_wb_sel (wb_mem_sel), .i_wb_dat (wb_mem_dat),
        .o_wb_rdt (wb_mem_rdt), .o_wb_ack (wb_mem_ack),
        .i_host_we (i_host_we), .i_host_adr (i_host_adr), .i_host_dat (i_host_dat));

    servant_timer #(.RESET_STRATEGY ("MINI"), .WIDTH (32)) timer (
        .i_clk (clk), .i_rst (core_rst), .o_irq (timer_irq),
        .i_wb_cyc (wb_timer_stb), .i_wb_we (wb_timer_we),
        .i_wb_dat (wb_timer_dat), .o_wb_dat (wb_timer_rdt));

    servant_gpio gpio (
        .i_wb_clk (clk), .i_wb_dat (wb_gpio_dat), .i_wb_we (wb_gpio_we),
        .i_wb_cyc (wb_gpio_stb), .o_wb_rdt (wb_gpio_rdt), .o_gpio (q));

    serv_rf_ram #(.width (rf_width), .csr_regs (csr_regs)) rf_ram (
        .i_clk (clk), .i_waddr (rf_waddr), .i_wdata (rf_wdata), .i_wen (rf_wen),
        .i_raddr (rf_raddr), .i_ren (rf_ren), .o_rdata (rf_rdata));

    servile #(.width (width), .sim (1'b0), .debug (1'b0), .with_c (1'b0),
              .with_csr (with_csr[0]), .with_mdu (1'b0)) cpu (
        .i_clk (clk), .i_rst (core_rst), .i_timer_irq (timer_irq),
        .o_wb_mem_adr (wb_mem_adr), .o_wb_mem_dat (wb_mem_dat),
        .o_wb_mem_sel (wb_mem_sel), .o_wb_mem_we (wb_mem_we),
        .o_wb_mem_stb (wb_mem_stb), .i_wb_mem_rdt (wb_mem_rdt),
        .i_wb_mem_ack (wb_mem_ack),
        .o_wb_ext_adr (wb_ext_adr), .o_wb_ext_dat (wb_ext_dat),
        .o_wb_ext_sel (wb_ext_sel), .o_wb_ext_we (wb_ext_we),
        .o_wb_ext_stb (wb_ext_stb), .i_wb_ext_rdt (wb_ext_rdt),
        .i_wb_ext_ack (wb_ext_ack),
        .o_rf_waddr (rf_waddr), .o_rf_wdata (rf_wdata), .o_rf_wen (rf_wen),
        .o_rf_raddr (rf_raddr), .o_rf_ren (rf_ren), .i_rf_rdata (rf_rdata));
endmodule

`default_nettype wire
