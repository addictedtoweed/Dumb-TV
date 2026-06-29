# Dev environment setup

The simulation stack is **Verilator + cocotb**. The reliable way to run it on
this Windows machine is **WSL (Ubuntu)** — MSYS2 was a dead end because its
mingw64 Python moved to 3.14, and cocotb 2.x only supports Python ≤ 3.13.

## 1. Install WSL (once)

In an **Administrator** PowerShell:

```powershell
wsl --install -d Ubuntu
```

Reboot when prompted. On first launch, Ubuntu asks for a UNIX username and
password (that password is what `sudo` uses).

## 2. Toolchain + Python deps (inside Ubuntu)

```sh
sudo apt update
sudo apt install -y verilator make python3 python3-venv g++
verilator --version          # expect 5.x (Ubuntu 24.04 ships 5.020)

python3 -m venv ~/dumbtv-venv
source ~/dumbtv-venv/bin/activate
pip install cocotb
```

> If `verilator --version` reports **4.x**, it's too old for cocotb 2.x. Install
> the **OSS CAD Suite** (YosysHQ prebuilt bundle, includes a recent Verilator),
> extract it, and prepend its `bin/` to your `PATH` instead of the apt package.

## 3. Run the tests

The repo lives on the Windows drive, reachable from WSL at `/mnt/c/...`:

```sh
cd "/mnt/c/Users/IP Freely/Documents/Source/Dumb-TV"

# compositor pipeline
make

# UART control plane
make TOPLEVEL=top_uart MODULE=test_uart
```

Each `make` run elaborates one top-level. `make clean` removes `sim_build/`.

## Notes / gotchas

- Re-activate the venv (`source ~/dumbtv-venv/bin/activate`) in every new shell
  before running `make`, or cocotb won't be found.
- Line endings: `.gitattributes` forces LF on sources so the Makefile and shell
  heredocs work under both WSL and MSYS2.
- The cocotb tests are self-checking against Python models of the exact
  gradient/blend/CRC math; a passing run means the RTL matches the spec.
