"""No-filesystem, no-provider regression tests for D2 Beads ignore review."""
import unittest

from experiments.dogfooding.d2.gitignore_review import review_beads_gitignore

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


if __name__ == "__main__":
    unittest.main()
