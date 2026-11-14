# Existing-board examples

Specs for working on boards boardwright did not make. The boards themselves
are demo projects that ship with KiCad, under their own licences, so they are
not copied here: copy each demo folder from your KiCad install next to the
spec.

KiCad keeps its demos in `share/kicad/demos/`:

| System | Folder |
|---|---|
| Linux package | `/usr/share/kicad/demos/` |
| Linux Flatpak | `/var/lib/flatpak/app/org.kicad.KiCad/current/active/files/share/kicad/demos/` |
| macOS | `/Applications/KiCad/KiCad.app/Contents/SharedSupport/demos/` |
| Windows | `C:\Program Files\KiCad\<version>\share\kicad\demos\` |

| Here | KiCad demo | What the spec does |
|---|---|---|
| `stickhub/` | `stickhub` | `boardwright.py`: a `REVIEW` for the USB hub (pair matching, decoupling); `live_demo.py`: a harmless first edit (one ground via and track) for `boardwright live apply` |
| `stickhub_schematic/` | `stickhub` | `add_demo.py`: add two parts to the existing schematic with `boardwright sch DIR add` |
| `complex_hierarchy/` | `complex_hierarchy` | `add_demo.py`: add a part on the root sheet of a hierarchical schematic |

For example:

```sh
cp -r /usr/share/kicad/demos/stickhub/* examples/existing/stickhub/
boardwright existing examples/existing/stickhub info
boardwright existing examples/existing/stickhub review
```

Then follow "First contact with a board you did not make" in
the [guide](https://heibench.com/boardwright/guide/).
