# Dev environment setup

The simulation stack is **Verilator + cocotb**, run under **WSL (Ubuntu)**.
This file records the exact working setup, including the version pitfalls we hit.

## The version pitfalls (why the steps look the way they do)

- **Python**: Ubuntu 26.04 (and current MSYS2) ship **Python 3.14**, but cocotb
  only supports **≤ 3.13**. We install a standalone **Python 3.13** with `uv`.
- **Verilator vs cocotb**: apt's Verilator is **5.032**, but cocotb **2.x**
  requires **≥ 5.036**. So we use **cocotb 1.9.x**, which is fine with 5.032.
- **Spaces in the path**: the repo lives under `.../IP Freely/...`. `make` and
  Verilator both choke on spaces, so the Makefile uses relative source paths and
  the build directory is redirected to a space-free location (`/tmp/...`).
  `sim.sh` handles this for you.

## 1. Install WSL (once, Administrator PowerShell)

```powershell
wsl --install -d Ubuntu
```

Reboot; set a UNIX username/password on first launch.

## 2. Verilator (needs sudo)

```sh
sudo apt update && sudo apt install -y verilator
verilator --version        # 5.032 is what we tested against
```

## 3. Python 3.13 + cocotb (no sudo)

```sh
# uv: standalone Python/venv manager
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

uv python install 3.13
uv venv ~/dumbtv-venv --python 3.13
uv pip install --python ~/dumbtv-venv/bin/python "cocotb<2"
```

## 4. Run the tests

```sh
cd "/mnt/c/Users/IP Freely/Documents/Source/Dumb-TV"

./sim.sh                                     # compositor pipeline  (2 tests)
./sim.sh TOPLEVEL=top_uart MODULE=test_uart  # UART control plane   (4 tests)
```

`sim.sh` activates the venv and sets a space-free `SIM_BUILD`. Expected result:
both suites report `PASS=N FAIL=0`.

## Notes

- New shell? `sim.sh` re-activates the venv itself, so you can just run it.
- `make clean` from the repo won't touch the `/tmp` build dirs; remove them with
  `rm -rf /tmp/dumbtv_build_*` if you want a fully clean rebuild.
- If you ever upgrade to a Verilator ≥ 5.036 (e.g. via the OSS CAD Suite), you
  can move back to `cocotb` 2.x by reinstalling without the `<2` pin.
