"""No-filesystem, no-provider regression tests for D2 Beads ignore review."""
import unittest

from experiments.dogfooding.d2.gitignore_review import (review_beads_gitignore, review_ignored_paths)

BASE = "__pycache__/\n*.py[cod]\n"
ADDED = "\n# Beads / Dolt files (added by bd init)\n.dolt/\n*.db\n.beads-credential-key\n.beads/proxieddb/\n*.gate.lock*\n"
FROZEN = BASE + ADDED


class D2GitignoreReviewTests(unittest.TestCase):
    def test_exact_operator_reported_five_patterns(self):
        report = review_beads_gitignore(BASE, FROZEN, FROZEN)
        self.assertEqual(report["decision"], "D2_BEADS_GITIGNORE_REVIEW_PASS")
        self.assertEqual(set(report["added_rules"]), {
            ".dolt/", "*.db", ".beads-credential-key",
            ".beads/proxieddb/", "*.gate.lock*",
        })
        self.assertEqual(report["broad_patterns_need_preworker_ignored_path_audit"],
                         ["*.db", "*.gate.lock*"])

    def test_snapshot_change_fails_before_any_commit(self):
        with self.assertRaisesRegex(ValueError, "changed after"):
            review_beads_gitignore(BASE, FROZEN + "# new\n", FROZEN)

    def test_unknown_ignore_rule_fails_closed_even_with_rewritten_snapshot(self):
        bad = FROZEN + "secrets/\n"
        with self.assertRaisesRegex(ValueError, "not equal"):
            review_beads_gitignore(BASE, bad, bad)

    def test_blanket_beads_ignore_fails_closed(self):
        bad = FROZEN + ".beads/\n"
        with self.assertRaises(ValueError):
            review_beads_gitignore(BASE, bad, bad)

    def test_blanket_projectctl_ignore_fails_closed(self):
        bad = FROZEN + ".projectctl/\n"
        with self.assertRaises(ValueError):
            review_beads_gitignore(BASE, bad, bad)

    def test_duplicate_added_rule_fails_closed(self):
        bad = FROZEN + "*.db\n"
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            review_beads_gitignore(BASE, bad, bad)

    def test_removing_original_baseline_rule_fails_closed(self):
        bad = FROZEN.replace("*.py[cod]\n", "")
        with self.assertRaisesRegex(ValueError, "Original"):
            review_beads_gitignore(BASE, bad, bad)

    def test_reordering_original_baseline_lines_fails_closed(self):
        bad = FROZEN.replace(BASE, "*.py[cod]\n__pycache__/\n")
        with self.assertRaisesRegex(ValueError, "Original"):
            review_beads_gitignore(BASE, bad, bad)

    def test_comment_only_additions_allowed_if_snapshot_matches(self):
        x = FROZEN + "# additional note\n\n"
        self.assertEqual(review_beads_gitignore(BASE, x, x)["decision"],
                         "D2_BEADS_GITIGNORE_REVIEW_PASS")

    def test_ignored_metadata_paths_allowed(self):
        review_ignored_paths([".beads/embeddeddolt/abc.db", ".beads/proxieddb/test",
                              ".dolt/config.json", ".beads-credential-key"])

    def test_observed_root_beads_gate_lock_allowed(self):
        review_ignored_paths([".beads.gate.lock"])
        review_ignored_paths([".beads.gate.lock", ".beads/embeddeddolt/abc.db"])

    def test_similar_root_gate_lock_names_still_rejected(self):
        for p in (".beads.gate.lock.backup", ".beads.gate.lock2",
                  "other.beads.gate.lock", ".BEADS.gate.lock",
                  ".beads.gate.lock/subfile", "nested/.beads.gate.lock"):
            with self.subTest(path=p):
                with self.assertRaisesRegex(ValueError, "outside Beads"):
                    review_ignored_paths([p])

    def test_other_root_gate_lock_unrelated_to_beads_still_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside Beads"):
            review_ignored_paths(["project.gate.lock"])

    def test_broad_db_pattern_must_not_hide_application_file(self):
        with self.assertRaisesRegex(ValueError, "outside Beads"):
            review_ignored_paths(["d2events/silent.db"])

    def test_broad_gate_lock_pattern_must_not_hide_application_file(self):
        with self.assertRaisesRegex(ValueError, "outside Beads"):
            review_ignored_paths(["out.gate.lock123"])

    def test_other_hidden_sources_are_not_exempt(self):
        with self.assertRaises(ValueError):
            review_ignored_paths(["d2events/__pycache__/cli.cpython-310.pyc"])


if __name__ == "__main__":
    unittest.main()
