Put your own legally obtained ROM dumps here. This folder is git-ignored, but this file.

| File | Version | Size |
|---|---|---|
| `Banjo-Kazooie (USA).z64` | US v1.0, `.z64` byte order, SHA-1 `1fe1632098865f639e22c11b9a81ee8f29c75d7a` | 16 MiB |

`hack/build_bk_rom.sh` copies it into the decompilation fork as its base ROM. The Tooie hack's build wants its own copy
of Banjo-Tooie (USA) as `hack/bt/n64/rom/Banjo-Tooie.z64` ([docs/BUILDING.md](../docs/BUILDING.md)).

The images land here too, each exactly 64 MiB: `bkbt2-normal.z64` is the one to play, and the other `bkbt2-*.z64`
are test images that switch games by themselves.
