# 09 existing schematic: StickHub

**What it is:** the StickHub demo's schematic (one sheet, 140 placed symbols,
470 wires, 26 labels, its own symbol library), in `dogfood/existing/schtest/`.

**Stresses:** changing a schematic nobody here drew, without redrawing it.

**What was done**
- `set R1 Value=22k`
- `add`: C99 (copy of C2) from +3.3V to GND; R99 (copy of R1) from the
  existing labelled net LED3 to a new net TESTNET.
- `remove R99`, on a scratch copy: the part goes, its stubs stay.

**KiCad's verdict** (`netdiff` between its netlists before and after):

    + part C99  100n  footprints:1005_C
    + part R99  4.7k  footprints:R_1005_C
    ~ part R1  10k -> 22k
    + net /TESTNET: R99.2
    ~ net +3.3V: +C99.1
    ~ net /LED3: +R99.1
    ~ net GND: +C99.2

Nothing else changed. ERC went from 94 findings to 97: two of the same
"footprint library not configured" kind the copy already had 94 of (this
test copy carries no footprint library), and "label connected to only one
pin" for TESTNET, which is true.

**What broke on the way**
1. First placement put the parts on the sheet's frame line: "right of
   everything drawn" is off the page on a full sheet. Now an occupancy grid
   finds an empty area inside the frame, clear of the title block.
2. A bounding box of the drawing called the sheet full when it was not.
3. Copied parts kept the source part's field offsets and rotation text, which
   landed on top of the symbol. The copy is now unrotated with reference and
   value beside it; power symbols keep their own layout.
4. A label pointing down has to be right-justified or its text runs back over
   the part.

**How it works:** no parse-and-rewrite. The file is searched for the block to
change and only that span is replaced; a new part is a renumbered copy of an
existing block, so the file's own format version comes along. Connection is
by label or by a copy of the net's power symbol, which KiCad joins by name.

**Left open**
- A part whose symbol is not already on the sheet cannot be added.
- Sub-sheets: `set` and `remove` reach them, `add` does not; a sheet used
  more than once is not handled.
- Nothing is wired point to point, moved, or deleted along with a part.
- The board is not updated from the schematic; that is done in KiCad.
- Tested on one schematic, in one KiCad file-format version.
