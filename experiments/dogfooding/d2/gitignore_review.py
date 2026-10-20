"""Strict offline D2 Beads .gitignore review for the recorded 1.3.1 setup.

Do not silently broaden allowed patterns or normalize the original file: the
operator's initial Beads snapshot is authoritative. A later preworker gate must
check ignored files, since broad *.db and *.gate.lock* can hide unrelated writes.
"""
from __future__ import annotations

from collections import Counter

BEADS_1_3_1_ADDITIONS = frozenset({
    ".dolt/",
    "*.db",
    ".beads-credential-key",
    ".beads/proxieddb/",
    "*.gate.lock*",
})
BROAD_ROOT_PATTERNS = frozenset({"*.db", "*.gate.lock*"})


def review_beads_gitignore(
    baseline_text: str,
    current_text: str,
    frozen_beads_snapshot_text: str,
) -> dict:
    """Verify original tracked content plus exactly observed Beads-init additions.

    No extra Git ignore rules, missing original lines, duplicated additions,
    changed snapshot, blanket .beads/ masking, or .projectctl/ masking.
    """
    if current_text != frozen_beads_snapshot_text:
        raise ValueError("Beads .gitignore changed after captured setup snapshot")
    original = baseline_text.splitlines()
    current = current_text.splitlines()
    position = 0
    for line in current:
        if position < len(original) and line == original[position]:
            position += 1
    if position != len(original):
        raise ValueError("Original .gitignore lines removed, edited, or reordered")
    counts = Counter(current) - Counter(original)
    added = list(counts.elements())
    rules = [line.strip() for line in added if line.strip() and
             not line.lstrip().startswith("#")]
    if len(rules) != len(set(rules)):
        raise ValueError("Duplicate added Beads ignore rules")
    if set(rules) != BEADS_1_3_1_ADDITIONS:
        raise ValueError(
            "Beads ignore additions not equal to pinned 1.3.1 operator snapshot: "
            + repr(sorted(rules))
        )
    if ".beads/" in rules or ".projectctl/" in rules:
        raise ValueError("Unexpected blanket ignore of Beads or ProjectCTL")
    return {
        "decision": "D2_BEADS_GITIGNORE_REVIEW_PASS",
        "baseline_rules": original,
        "added_rules": sorted(rules),
        "snapshot_exact_match": True,
        "original_tracked_lines_preserved": True,
        "broad_patterns_need_preworker_ignored_path_audit": sorted(
            BROAD_ROOT_PATTERNS.intersection(rules)
        ),
    }


def review_ignored_paths(paths: list[str]) -> None:
    """Reject silently ignored application files before committing broad rules."""
    unexpected = [
        p for p in paths
        if not (
            p.startswith(".beads/")
            or p.startswith(".dolt/")
            or p == ".beads-credential-key"
        )
    ]
    if unexpected:
        raise ValueError(
            "Ignored paths outside Beads operational metadata: "
            + repr(sorted(unexpected))
        )
