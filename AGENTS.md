# AGENTS.md — boardwright

Generate and edit KiCad boards and schematics from a short Python description,
checked by KiCad itself. How to *use* it is in `docs/guide.md`; this file is
for changing it.

## Rules

1. **KiCad is the judge.** A feature is done when KiCad's own output (ERC, DRC
   with schematic parity, netlist) agrees, not when the tool's arithmetic says
   so. Connectivity checks belong to netspec; do not grow a second copy here.
2. **Edit, do not rewrite.** Changes to a user's existing files replace the one
   block they mean to change and leave the rest byte-identical, and are
   written only if the file is still what was read.
3. **Design for the people and tools that run it.** No flag, mode, message or
   doc exists to suit one machine or one way of driving the tool. Machine
   locations go through `src/boardwright/env.py`, set by an environment
   variable or found in standard install places.
4. **Numbers carry their source.** A threshold, cost or limit in the code or
   docs says where it was measured or which document it came from.
5. **Exit codes are the heibench contract** (`src/boardwright/errors.py`):
   0 done, 1 refused or violated, 2 could not tell, 4 environment fault, 64
   usage. A missing tool or report is never reported as a finding about the
   design. The org-wide rules are in
   [heibench/.github AGENTS.md](https://github.com/heibench/.github/blob/main/AGENTS.md);
   this file wins where they conflict.
6. **Limits are stated.** What the tool does badly is listed in
   `docs/guide.md` and `docs/devlog/gaps.md`; keep both true.

## Workflow

`just check && just test` before every commit. Conventional Commits. Tests
that need KiCad, its libraries or Freerouting skip where they are missing; CI's
`KiCad pipeline` job runs them against a real KiCad 10 and fails if they skip.

A change found by working on a real board gets an entry in `docs/devlog/`.

## Related

`netspec` (heibench/netspec) is the read-only gate: it never writes a design
file. boardwright is the writer and uses netspec to check connectivity.
`gerberdiff` compares fabrication output.
