"""Where the agent skill is: `boardwright --docs` prints the directory that
holds `skills/` (#48), so an agent runs `cd "$(boardwright --docs)"` and reads
`skills/boardwright/SKILL.md` for the version it has installed."""

from __future__ import annotations

from pathlib import Path

SKILL = Path("skills") / "boardwright" / "SKILL.md"


def docs_root() -> Path | None:
    """The bundled copy in an installed wheel, else the checkout this file sits
    in (an editable install, where nothing was copied). None when neither holds
    the skill: no guessing at another directory."""
    package = Path(__file__).resolve().parent
    for root in (package / "_bundled", package.parent.parent if package.parent.name == "src" else None):
        if root is not None and (root / SKILL).is_file():
            return root
    return None
