# Toolchain setup and reproducibility

Web dependencies are locked in `requirements.lock.txt`. They do not install Torch, NumPy, EDA binaries, Nix, PYNQ or external BM repositories. Configure each execution environment independently and retain actual version probes with every qualification run.

## Linear / candidate X2

Set `COMPILER_MODEL_REPO`, `COMPILER_X1_REPO`, `COMPILER_PYTHON`, `IVERILOG_PATH`, `VVP_PATH`, `YOSYS_PATH` and optionally `ABC_PATH`. The external Python must import the required BM/V2 modules and numerical dependencies. Use `python manage.py compiler_inventory` to inspect availability; paths alone are not successful probes.

The tested installation includes native Windows tools and WSL-based adapters. `COMPILER_WSL_DISTRO` identifies the Linux environment used where a tool path requires WSL. Native executables should use absolute Windows paths. The compiler worker executes bounded commands with a restricted environment.

## FABulous reference

Configure `FABULOUS_WSL_DISTRO`, `FABULOUS_WSL_USER`, `FABULOUS_VENV`, `FABULOUS_CAD_BIN`, `FABULOUS_WORK_ROOT` and `FABULOUS_HOST_STORAGE`. The existing reference environment used FABulous 2.2.0; keep its compatible tools separate from the SKY130 Nix environment.

The work directory is a configured Linux build location exposed to the Windows host. Available host disk space matters because the WSL virtual disk grows on the host filesystem. The upstream reference result does not qualify a BM physical target.

## SKY130 ReRAM Nix environment

Follow the [pinned upstream user-design instructions](https://github.com/mole99/sky130-reram-fpga/tree/e0790eb11a1e95914f2beb8f175396a0924144ed/user_designs). Install Nix and configure the upstream FOSSi cache according to those instructions. Pin both the main checkout and its submodule revisions.

```bash
git clone https://github.com/mole99/sky130-reram-fpga.git
cd sky130-reram-fpga
git checkout e0790eb11a1e95914f2beb8f175396a0924144ed
git submodule update --init --recursive
cd user_designs
nix-shell
cd designs/classic/counter
make synth
make pnr
make bitstream
make hex
```

Repository/submodule access is required. The user-design compilation needs the pinned fabulous-tiles primitives, extra ReRAM synthesis primitive and generated target data. Full fabric simulation needs additional generated tile sources; do not treat the compile instructions as a complete simulation setup.

The qualified toolchain used Yosys 0.70, nextpnr `3e53a0bf`, Python 3.13.13 and FASM 0.0.2. An earlier Yosys 0.66+179 rejected the required synthesis options. FASM may warn that its optional fast parser is unavailable and use textX; retain that warning and check actual conversion results.

For the web workflow, copy `deploy/sky130-user-design.example.json` to `deploy/sky130-user-design.json`. Fill the WSL distribution/user, absolute repository path and the actual Nix tool PATH. Exclude relative PATH entries and retain Nix garbage-collection roots for deployed runtime paths. Nix store paths are installation-specific and are not portable credentials or universal examples.

For the standalone adapter, from this application's root in Linux:

```bash
python3 -m compiler.sky130_user_design \
  --repo /absolute/path/to/sky130-reram-fpga \
  --output /absolute/path/to/a-new-evidence-directory \
  --design counter \
  --tool-path /actual/nix/tool/bin:/actual/python-env/bin:/usr/bin:/bin
```

Use a new output directory. `--design reram_cim_32x32` runs the upstream primitive-instantiation example; it is not a numerical ReRAM test. Never pass uploaded repositories/Makefiles as trusted administrator inputs.
