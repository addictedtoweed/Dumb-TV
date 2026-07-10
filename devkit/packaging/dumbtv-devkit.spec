# PyInstaller spec for a zero-install Dumb-TV dev-kit bundle.
#
#   pip install pyinstaller
#   pyinstaller packaging/dumbtv-devkit.spec        # run from the devkit/ dir
#
# Produces dist/dumbtv-devkit/ -- a self-contained folder (no Python needed) with
# the app, the firmware images (fw/), and an empty videos/ to drop vid_0..vid_15
# into. Zip it and attach it to a GitHub Release. onedir keeps LGPL libs (pygame,
# FFmpeg) as separate replaceable files -- see ../NOTICE.

import os

block_cipher = None
DEVKIT = os.path.abspath(os.path.join(os.getcwd()))
FW = os.path.join(DEVKIT, "..", "fw")

datas = [(os.path.join(DEVKIT, "videos", "README.md"), "videos"),
         (os.path.join(DEVKIT, "README.md"), "."),
         (os.path.join(DEVKIT, "LICENSE"), "."),
         (os.path.join(DEVKIT, "NOTICE"), ".")]
datas += [(os.path.join(FW, b), "fw")
          for b in os.listdir(FW) if b.endswith(".bin")]

a = Analysis(["app.py"], pathex=[DEVKIT], binaries=[], datas=datas,
             hiddenimports=["dumbtv_sim.riscv", "dumbtv_sim.ir"],
             hookspath=[], runtime_hooks=[], excludes=[],
             cipher=block_cipher, noarchive=False)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="dumbtv-devkit",
          debug=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False,
               name="dumbtv-devkit")
