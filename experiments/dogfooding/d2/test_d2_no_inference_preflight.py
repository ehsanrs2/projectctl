"""Pure offline tests for D2 paid-run preflight; never starts Codex or ProjectCTL."""
import hashlib
import unittest

from experiments.dogfooding.d2.d2_no_inference_preflight import (
    ALLOWED_WRITES, CODEX_CLI, EXPECTED_FLAGS, ORDER,
    direct_prompt, validate_cli_help, validate_strategy,
)

def base_caps():
    support = {"runtime": "supported", "adapter": "supported"}
    return {
        "probe_kind": "version_only",
        "runtime": {
            "sdk_name": "openai-codex",
            "sdk_version": "0.160.0",
            "runtime_version": "0.160.0",
            "adapter_version": "0.41.0",
        },
        "modes": {"default": support.copy()},
        "permissions": {
            "sandboxes": {"workspace_write": support.copy()},
            "approvals": {"deny_all": support.copy()},
        },
    }

def base_strategy():
    return {
        "task_id": "d2ctl-g4q",
        "requested": "direct",
        "resolved": "direct",
        "compatible": True,
        "fallback_used": False,
        "unsupported": [],
        "planning": None,
        "execution": {
            "approval": "deny_all",
            "mode": "default",
            "network": "disabled",
            "sandbox": "workspace_write",
        },
    }


class D2PreflightContractTests(unittest.TestCase):
    def test_frozen_arm_order_and_three_paths(self):
        self.assertEqual(ORDER, ("direct_cli", "projectctl"))
        self.assertEqual(ALLOWED_WRITES,
                         ("d2events/cli.py", "d2events/parse.py", "d2events/report.py"))

    def test_direct_prompt_is_deterministic_and_contains_original_sources(self):
        p = direct_prompt("MY SPEC\n", "MY POLICY\n")
        self.assertEqual(p, direct_prompt("MY SPEC\n", "MY POLICY\n"))
        self.assertIn("\n=== SPEC.md ===\nMY SPEC\n", p)
        self.assertIn("\n=== POLICY.md ===\nMY POLICY\n", p)
        self.assertIn("Only modify d2events/parse.py", p)
        self.assertNotIn("ProjectCTL worker", p)
        self.assertEqual(hashlib.sha256(p.encode()).hexdigest(),
                         hashlib.sha256(direct_prompt("MY SPEC\n", "MY POLICY\n").encode()).hexdigest())

    def test_strategy_accepts_frozen_direct(self):
        validate_strategy(base_caps(), base_strategy())

    def test_version_only_capability_required(self):
        c = base_caps()
        c["probe_kind"] = "live"
        with self.assertRaisesRegex(ValueError, "version-only"):
            validate_strategy(c, base_strategy())

    def test_unknown_or_unsupported_permission_refused(self):
        c = base_caps()
        c["permissions"]["sandboxes"]["workspace_write"]["adapter"] = "unknown"
        with self.assertRaisesRegex(ValueError, "permissions"):
            validate_strategy(c, base_strategy())

    def test_sdk_version_drift_refused(self):
        c = base_caps()
        c["runtime"]["sdk_version"] = "0.170.0"
        with self.assertRaisesRegex(ValueError, "SDK"):
            validate_strategy(c, base_strategy())

    def test_network_access_refused(self):
        s = base_strategy()
        s["execution"]["network"] = "enabled"
        with self.assertRaisesRegex(ValueError, "permissions drift"):
            validate_strategy(base_caps(), s)

    def test_fallback_refused(self):
        s = base_strategy()
        s["fallback_used"] = True
        with self.assertRaisesRegex(ValueError, "not strictly compatible"):
            validate_strategy(base_caps(), s)

    def test_wrong_task_refused(self):
        s = base_strategy()
        s["task_id"] = "D1-not-D2"
        with self.assertRaisesRegex(ValueError, "not strictly compatible"):
            validate_strategy(base_caps(), s)

    def test_cli_pinned_help_accepts_all_options(self):
        validate_cli_help(CODEX_CLI, "--disable", " ".join(EXPECTED_FLAGS))

    def test_cli_version_mismatch_refused(self):
        with self.assertRaisesRegex(ValueError, "version drift"):
            validate_cli_help("codex-cli 0.169.0", "--disable", " ".join(EXPECTED_FLAGS))

    def test_cli_missing_flag_refused(self):
        with self.assertRaisesRegex(ValueError, "lacks pinned"):
            validate_cli_help(CODEX_CLI, "--disable", " ".join(EXPECTED_FLAGS[1:]))

    def test_cli_missing_plugin_disable_refused(self):
        with self.assertRaisesRegex(ValueError, "lacks pinned"):
            validate_cli_help(CODEX_CLI, "help", " ".join(EXPECTED_FLAGS))


if __name__ == "__main__":
    unittest.main()
