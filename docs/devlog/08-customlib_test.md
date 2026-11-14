# 08 customlib_test

**What it is:** a five-part regulator board whose regulator symbol and
footprint come from `dogfood/customlib/`, a stand-in for a private library
(stock parts copied and renamed so the names exist nowhere else).

**Stresses:** `LIBS`.

**What happened**
- `LIBS = ["../../dogfood/customlib"]` builds a merged view of stock and
  custom libraries under `.libmerge/` and points lookup, vendoring and the pin
  lister at it. ERC 0, DRC 0 including parity and library checks.
- The custom symbol `extends` a stock one; the trimmer carries the parent along.
- Pointing the part at a 3-pad footprint is refused before generation:
  "pins ['4', '5'] have no pad".

**Left open**
- Not tried against a large real library, or one that uses KiCad path
  variables in 3D model references.
- A custom library that shadows a stock one by name replaces it silently.
