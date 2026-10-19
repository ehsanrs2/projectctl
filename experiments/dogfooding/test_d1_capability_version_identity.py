"""D1-R1 regression tests for version-only vs live Codex capability snapshots.

These tests are offline; no live Codex App Server or model execution is invoked.
"""
from datetime import datetime, timedelta, timezone
import unittest

from projectctl.core.enums import CapabilityState, WorkerMode
from projectctl.workers.capability_digest import (
    effective_capability_digest,
    runtime_version_identity,
)
from projectctl.workers.codex.adapter import CodexWorkerAdapter

PREPARED_VERSION = "0.160.0"
OBSERVED_LIVE_BANNER = (
    "0.160.0 (Ubuntu 24.4.0; x86_64) "
    "Konsole/230805 (projectctl; 0.41.0)"
)


class D1CapabilityVersionEquivalenceTests(unittest.TestCase):
    def setUp(self):
        # Version-only probe is a local package/CLI metadata read, not live inference.
        baseline = CodexWorkerAdapter.version_capabilities()
        self.prepared = baseline.model_copy(
            update={"runtime": baseline.runtime.model_copy(
                update={"runtime_version": PREPARED_VERSION}
            )}
        )

    def live(self, runtime_version=OBSERVED_LIVE_BANNER):
        runtime = self.prepared.runtime.model_copy(
            update={
                "runtime_version": runtime_version,
                "observed_at": datetime.now(timezone.utc) + timedelta(seconds=10),
            }
        )
        return self.prepared.model_copy(
            update={"probe_kind": "live_runtime", "runtime": runtime}
        )

    def test_operator_observed_banner_has_same_effective_digest(self):
        live = self.live()
        self.assertEqual(
            effective_capability_digest(self.prepared),
            effective_capability_digest(live),
        )
        # Raw probe evidence remains intact, including platform and user agent.
        self.assertEqual(live.runtime.runtime_version, OBSERVED_LIVE_BANNER)
        self.assertEqual(self.prepared.runtime.runtime_version, PREPARED_VERSION)

    def test_canonical_version_from_exact_operator_observation(self):
        self.assertEqual(
            runtime_version_identity(OBSERVED_LIVE_BANNER),
            PREPARED_VERSION,
        )

    def test_real_runtime_upgrade_still_changes_digest(self):
        self.assertNotEqual(
            effective_capability_digest(self.prepared),
            effective_capability_digest(self.live(
                "0.161.0 (Ubuntu 24.4.0; x86_64) Konsole/230805"
            )),
        )

    def test_prerelease_identifier_is_not_hidden(self):
        self.assertEqual(
            runtime_version_identity("0.160.0-rc.1 (Ubuntu 24.4.0; x86_64)"),
            "0.160.0-rc.1",
        )
        self.assertNotEqual(
            effective_capability_digest(self.prepared),
            effective_capability_digest(self.live(
                "0.160.0-rc.1 (Ubuntu 24.4.0; x86_64)"
            )),
        )

    def test_build_identifier_is_not_hidden(self):
        self.assertEqual(
            runtime_version_identity("0.160.0+build2 (Ubuntu 24.4.0; x86_64)"),
            "0.160.0+build2",
        )
        self.assertNotEqual(
            effective_capability_digest(self.prepared),
            effective_capability_digest(self.live(
                "0.160.0+build2 (Ubuntu 24.4.0; x86_64)"
            )),
        )

    def test_sdk_version_change_still_changes_digest(self):
        modified = self.live()
        changed_runtime = modified.runtime.model_copy(
            update={"sdk_version": "0.161.0"}
        )
        modified = modified.model_copy(update={"runtime": changed_runtime})
        self.assertNotEqual(
            effective_capability_digest(self.prepared),
            effective_capability_digest(modified),
        )

    def test_capability_support_change_still_changes_digest(self):
        modified = self.live()
        modes = dict(modified.modes)
        modes[WorkerMode.DEFAULT] = modes[WorkerMode.DEFAULT].model_copy(
            update={"adapter": CapabilityState.UNSUPPORTED}
        )
        modified = modified.model_copy(update={"modes": modes})
        self.assertNotEqual(
            effective_capability_digest(self.prepared),
            effective_capability_digest(modified),
        )

    def test_unrecognized_unparenthesized_suffix_fails_closed(self):
        suspicious = "0.160.0 unrecognized-metadata"
        self.assertEqual(runtime_version_identity(suspicious), suspicious)
        self.assertNotEqual(
            effective_capability_digest(self.prepared),
            effective_capability_digest(self.live(suspicious)),
        )

    def test_none_preserved(self):
        self.assertIsNone(runtime_version_identity(None))


if __name__ == "__main__":
    unittest.main()
