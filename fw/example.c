/* example.c -- boilerplate Dumb-TV SERV firmware.
 *
 * A minimal program showing the shape: bring up the software UART, then issue
 * TV commands over the internal link exactly as a host would. This example
 * selects an input and nudges the backlight, then parks.
 *
 * Build:   ./build.sh example.c firmware
 * Upload:  python ../host/dumbtv.py ...   (or DumbTV.load_firmware(open('firmware.bin','rb').read()))
 *
 * SPDX-License-Identifier: CC0-1.0
 */
#include "dumbtv.h"

int main(void)
{
    dumbtv_uart_init();             /* raise the line to idle, settle */

    dumbtv_input_select(1);         /* switch the TV to input 1 */
    dumbtv_backlight(200);          /* ~78% backlight */

    for (;;) {
        /* A real build would poll the IR GPIO here and translate remote codes
         * into dumbtv_* commands. For now, just park. */
    }
    return 0;
}
