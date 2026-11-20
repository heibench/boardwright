"""Every third-party action runs at a fixed commit (#84)."""

import re

from conftest import ROOT

PIN = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+$")
USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(.+?)\s*$", re.MULTILINE)


def unpinned(text: str) -> list[str]:
    return [ref for ref in USES.findall(text) if not ref.startswith("./") and not PIN.match(ref)]


def test_every_action_in_every_workflow_is_pinned_to_a_sha():
    """A tag can be moved to other code; a commit SHA cannot. release.yml holds
    the PyPI publishing identity, and the other workflows run on every push.

    A full SHA with the version in a trailing comment, in every workflow, as
    heibench/netspec#55 settled: Dependabot bumps such a pin SHA-for-SHA and
    rewrites the comment, majors included, so its PRs pass here unaided. An
    exact tag it can rewrite to a floating major (heibench/netspec#32), and
    some actions no longer publish major tags at all (setup-uv has v7 but no
    v10). Local actions (`./`) are this repo's own code and are exempt."""
    found = {
        wf.name: bad
        for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
        if (bad := unpinned(wf.read_text()))
    }
    assert not found, f"pin to a full SHA with a `# vX.Y.Z` comment: {found}"


def test_the_gate_refuses_a_floating_major_a_bare_tag_and_a_sha_without_its_comment():
    sha = "3d3c42e5aac5ba805825da76410c181273ba90b1"
    refs = [
        "actions/checkout@v7",
        "actions/checkout@v7.0.1",
        f"actions/checkout@{sha}",
        f"actions/checkout@{sha} # v7",
    ]
    text = "".join(f"      - uses: {r}\n" for r in refs)
    assert unpinned(text) == refs
    ok = f"      - uses: actions/checkout@{sha} # v7.0.1\n        uses: ./.github/actions/local\n"
    assert unpinned(ok) == []
