<p align="center">
  <img src=".github/banner.svg" alt="Banjo-Kazooie & Tooie dual-boot image" width="100%">
</p>

<p align="center">
  <img alt="N64, 64 MiB" src="https://img.shields.io/badge/N64-64%20MiB%20image-f2b632">
  <img alt="Dual-boot contract 5" src="https://img.shields.io/badge/dual--boot%20contract-5-4aa8e0">
  <img alt="Status: alpha" src="https://img.shields.io/badge/status-alpha-e5604f">
  <a href="LICENSE"><img alt="MIT licence" src="https://img.shields.io/badge/licence-MIT-7b68ee"></a>
</p>

**One N64 cartridge image with Banjo-Tooie and Banjo-Kazooie on it, each able to start the other in the middle of
a game.** Walk into Gruntilda's Lair in Tooie's Spiral Mountain and Tooie saves, hands over to Banjo-Kazooie, and
Banjo-Kazooie comes up in its own Lair with your file loaded. Walk out and Tooie comes back the same way. It is the
ROM of the [Banjo-Kazooie & Tooie](https://github.com/kegan-dev/Archipelago-BanjoKazooieTooie) Archipelago world.

> [!NOTE]
> **Playing?** You don't need this repository. The Banjo-Kazooie & Tooie client builds the image from your own ROMs.
> This is where the image comes from, for anyone who wants to build it or work on it.

## What's in the image

```
cart 0x0000000  Banjo-Tooie with its Archipelago hack (our fork, hack 4.13.1)   32 MiB + the hack's payload
cart 0x2200000  the Banjo-Kazooie payload: the way back to Tooie                 64 KiB slot
cart 0x2210000  an info block for the tools
cart 0x3000000  Banjo-Kazooie with its Archipelago hack (our decomp fork)        16 MiB, not relocated
```

Only one game runs at a time. At a door the running game saves, writes where the player is going into a small
handoff block in RAM, and starts the other game, which skips its title and file select and arrives at the
destination behind a black, silent screen. Banjo-Kazooie runs from its new cart address by moving `osRomBase` alone.
Both games share one 32 KiB SRAM. [docs/CONTRACT.md](docs/CONTRACT.md) has the details: the layout, the handoff
block, the launch in each direction, the save device and the doors.

## The repositories it's built from

| Path | Repository | What |
|---|---|---|
| `hack/bt` | [AP-Banjo-Tooie](https://github.com/kegan-dev/AP-Banjo-Tooie) (submodule) | Banjo-Tooie's hack: Auztin's Banjo-Tooie AP hack with the dual-boot side added |
| `hack/bk/decomp` | [AP-Banjo-Kazooie](https://github.com/kegan-dev/AP-Banjo-Kazooie) (submodule) | Banjo-Kazooie's hack, built from a fork of the decompilation |
| `hack/bk/asm` | here | The payload that takes Banjo-Kazooie back to Tooie (armips) |
| `tools/make_dualboot_image.py` | here | Puts the image together, and refuses parts that don't belong together |
| `hack/build_*.sh` | here | The builds, in order |

## Building

```bash
git clone --recurse-submodules https://github.com/kegan-dev/AP-Banjo-Kazooie-Tooie.git
cd AP-Banjo-Kazooie-Tooie
bash hack/build_dualboot.sh normal        # roms/bkbt2-normal.z64
```

That needs your own ROMs and three toolchains. [docs/BUILDING.md](docs/BUILDING.md) walks through the setup. The
scripts were written for Windows (Git Bash, with a WSL 1 distro for the decompilation's build).

## Status

| | |
|---|---|
| Project64 3.0.1, ares v148 (Windows) | Played by hand, both directions, through the alpha's features |
| mupen64plus | Checked headlessly, with test builds that switch games by themselves |
| Console, flashcart | **Not tried.** No emulator models the N64's caches, so only a console would show some kinds of mistake |

## The Banjo repositories

| Repository | What it is |
|---|---|
| [Archipelago-BanjoKazooie](https://github.com/kegan-dev/Archipelago-BanjoKazooie) | The Banjo-Kazooie world and its client |
| [Archipelago-BanjoKazooieTooie](https://github.com/kegan-dev/Archipelago-BanjoKazooieTooie) | Both games in one slot: the combined world and its client |
| **AP-Banjo-Kazooie-Tooie** | This: the dual-boot image |
| [AP-Banjo-Kazooie](https://github.com/kegan-dev/AP-Banjo-Kazooie) | The Banjo-Kazooie ROM hack, a fork of the decompilation |
| [AP-Banjo-Tooie](https://github.com/kegan-dev/AP-Banjo-Tooie) | The Banjo-Tooie ROM hack, a fork of the Banjo-Tooie AP hack |

Issues about playing go to the world's repository. Issues about building or about the image itself go here.

## Credits

- [Auztin](https://github.com/Auztin/AP-Banjo-Tooie) and the Banjo-Tooie AP hack's contributors: the image's Tooie is
  their hack, with the dual-boot side added. [jjjj12212 and g0goTBC](https://github.com/jjjj12212/Archipelago-BanjoTooie)
  for the Banjo-Tooie AP world it serves.
- The [Banjo-Kazooie decompilation](https://gitlab.com/banjo.decomp/banjo-kazooie) project: Banjo-Kazooie's side is
  built from it.
- [CyrusKashef's BK_Randomizer](https://github.com/CyrusKashef/BK_Randomizer), for what it documents of the ROM.
- [Kingcom's armips](https://github.com/Kingcom/armips) and [libdragon](https://github.com/DragonMinded/libdragon)'s
  toolchain, which the builds use.

## Licence

The scripts, the payload and the tools here are [MIT](LICENSE). The submodules keep their own licences: the Tooie
hack MIT, the decompilation CC0. Banjo-Kazooie and Banjo-Tooie are trademarks of their owners; this project isn't
affiliated with them. No game data is in this repository; bring your own legally obtained ROMs.
