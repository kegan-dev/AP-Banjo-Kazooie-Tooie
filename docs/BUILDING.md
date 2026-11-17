# Building the image

The image is made of three builds that have to agree with each other: Banjo-Kazooie's hack, the Banjo-Kazooie payload
and Banjo-Tooie's hack. `hack/build_dualboot.sh` runs them in order and puts the image together. The scripts were
written for **Windows with Git Bash**, with a **WSL 1** distro for the decompilation's build; on Linux the same steps
work by hand (below).

## What you need

| | Where it goes | Notes |
|---|---|---|
| Banjo-Kazooie (USA) v1.0 | `roms/Banjo-Kazooie (USA).z64` | `.z64` byte order, SHA-1 `1fe1632098865f639e22c11b9a81ee8f29c75d7a` |
| Banjo-Tooie (USA) | `hack/bt/n64/rom/Banjo-Tooie.z64` | `.z64` byte order, MD5 `40e98faa24ac3ebe1d25cb5e5ddf49e4` |
| The MIPS toolchain | `hack/bt/n64/tools/mips64/opt/libdragon/` | `gcc-toolchain-mips64-win64.zip` from libdragon's `toolchain-continuous-prerelease` release (GCC 16), extracted so that `bin/mips64-elf-gcc.exe` is there |
| armips v0.11.0 | `hack/bt/n64/tools/armips/armips.exe` | [Kingcom/armips](https://github.com/Kingcom/armips) Windows release; the payload uses it too |
| Python 3.12 | `py -3.12` | With `bsdiff4` for the Tooie hack's patch: `py -3.12 -m pip install bsdiff4` |
| A WSL 1 distro named `bkdecomp` | | Ubuntu 22.04 with the decompilation's `packages.txt`, git and a Rust toolchain (`rustup`) |

Everything under `hack/bt/n64/tools/` and `hack/bt/n64/rom/` is git-ignored in the Tooie fork. Get the submodules with
the clone (`--recurse-submodules`) or afterwards:

```bash
git submodule update --init --recursive
```

The decompilation's build needs its own Python environment once, made inside WSL in the tree, as the decompilation's
README describes (`<repo>` is this repository's path seen from WSL, like `/mnt/c/src/AP-Banjo-Kazooie-Tooie`):

```bash
wsl -d bkdecomp -u root -- bash -lc 'cd <repo>/hack/bk/decomp && python3 -m venv .venv && .venv/bin/python3 -m pip install -r requirements.txt'
```

The first build also downloads the IDO compiler's recompilation and builds the decompilation's Rust tools.

## The build

```bash
bash hack/build_dualboot.sh normal        # roms/bkbt2-normal.z64, the image to play
```

It runs:

1. `hack/build_bk_rom.sh`: Banjo-Kazooie from the fork (`make BKBT=1` inside WSL), exported to `hack/bk/build/` as
   `bk-fork.z64` (its header says it saves to SRAM), `bk-fork.map` and `bk-fork.json`, the addresses the tools need.
   `--skip-bk` reuses the last export.
2. `hack/build_bk.sh`: the payload, `hack/bk/build/bk-payload.bin`.
3. `hack/build_bt.sh clean`: the Tooie hack, `hack/bt/n64/rom/Banjo-Tooie-Patched.z64`.
4. `tools/make_dualboot_image.py`: the 64 MiB image. It checks that the parts belong together (the contract number in
   each, the sizes, the save layout, Banjo-Kazooie's SHA-1 against its JSON) and refuses to write one that doesn't.

Each part builds alone too:

```bash
bash hack/build_bk_rom.sh             # Banjo-Kazooie's hack
bash hack/build_bk_rom.sh matching    # the unmodified game: must come out byte-identical to your ROM
bash hack/build_bk.sh                 # the payload
bash hack/build_bt.sh clean           # the Tooie hack
```

After a `matching` build, run `hack/build_bk_rom.sh` once more so that the tree holds the hack build again (switching
recompiles everything, about two minutes).

### Test images

The other variants build Tooie's hack with test flags. They switch games or walk through the doors by themselves,
for checks that run an emulator without a player:

```bash
bash hack/build_dualboot.sh autotest roundtrip soak3 retail-control door cross cheato normal
```

`hack/build_dualboot.sh` with no argument lists them. It always builds the normal Tooie hack again at the end, so
`hack/bt/n64/rom/` is never left holding a test build.

## Settings

| Variable | For |
|---|---|
| `PYTHON` | The interpreter for the tools (default `py -3.12`) |
| `BK_WSL_DISTRO` | Another WSL distro for the decompilation (default `bkdecomp`) |
| `BK_DECOMP_TREE` | Another checkout of the Banjo-Kazooie fork |
| `JOBS` | `make -j` for the decompilation (default 4) |
| `EXTRA_CFLAGS` | Flags for a one-off Tooie hack build (`bash hack/build_bt.sh clean`; build without them afterwards) |

## On Linux

The scripts call `wsl` and `cygpath`, so they don't run as they are. The steps do:

- Banjo-Kazooie: in `hack/bk/decomp`, with the decompilation's own setup, `make BKBT=1`; then write the SRAM header
  and the name (`tools/ed64romconfig.py -w sram256k`, `tools/rom_name.py --bk`) and the JSON
  (`tools/bk_fork_info.py`) into `hack/bk/build/`, as `hack/build_bk_rom.sh` does.
- The payload and the Tooie hack: libdragon's Linux toolchain and armips, with the same flags as the scripts.
- The image: `python3 tools/make_dualboot_image.py hack/bt/n64/rom/Banjo-Tooie-Patched.z64 -o roms/bkbt2-normal.z64`.

Patches that make the scripts work on Linux are welcome.
