"""Pure local tests for D2 Attempt-2 replay/preview; no provider or worker.

Uses only synthetic fixture JSON and tempfile evidence. No real D2 files are
written, no actual Codex App Server session, quota refresh or task claim.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from contextlib import redirect_stdout, redirect_stderr

from projectctl.core.digest import digest
from projectctl.core.errors import ProviderUnavailableError, QuotaError
from projectctl.quota import resolver
from projectctl.quota.manager import QuotaManager
from projectctl.schemas.config import QuotaPolicy
from projectctl.schemas.quota import QuotaSnapshot, QuotaWindow
from experiments.dogfooding.d2 import d2_ctl_attempt2_offline as h


def synthetic_payloads():
    observed=datetime(2026,10,21,8,13,53,465342,tzinfo=timezone.utc)
    official=QuotaSnapshot(
        provider="codex_app_server", account="synthetic-offline-account",
        observed_at=observed, selected_limit_id="codex",
        ordinary_usage_allowed=True,
        five_hour=QuotaWindow(remaining_ratio=.77, source="official",confidence="high"),
        weekly=QuotaWindow(remaining_ratio=.92, source="official",confidence="high"))
    unknown=h.unknown_quota_snapshot(official.account,official.provider)
    summary={
        "decision":h.EXPECTED_STATE,"reason":h.EXPECTED_ERROR,
        "attempt":1,"retries":0,"worker_started":False,
    }
    quota={"snapshot":official.model_dump(mode="json"),"mode":"normal",
           "stale":False,"effective":{"five_hour":.72,"weekly":.87}}
    scheduler={
        "evaluated_at":(observed+timedelta(milliseconds=456)).isoformat(),
        "quota_snapshot_digest":digest(unknown),
        "quota_mode":"conservation","selected_task_id":None,
        "candidates":[{
            "task_id":h.TASK,
            "eligibility":{"task_id":h.TASK,"eligible":False,
                           "reasons":["quota_unknown"]},
            "model":None,
        }],
    }
    return summary,quota,scheduler


def write_synthetic(folder: Path, payloads=None):
    folder.mkdir(parents=True,exist_ok=True)
    items=payloads or synthetic_payloads()
    for name,data in zip(h.REQUIRED,items):
        (folder/name).write_text(json.dumps(data,sort_keys=True)+"\n",
                                 encoding="utf-8")
    return items


class Attempt2ReplayOfflineTests(unittest.TestCase):
    def test_exact_unknown_fallback_digest_accepts(self):
        with TemporaryDirectory() as td:
            folder=Path(td)
            write_synthetic(folder)
            got=h.safe_historical_replay(folder)
            self.assertEqual(got["decision"],
                             "D2_ATTEMPT1_FALLBACK_REPLAY_PASS__NO_PROVIDER_CALLS")
            self.assertTrue(got["scheduler_equals_canonical_unknown"])
            self.assertFalse(got["scheduler_equals_official"])
            self.assertFalse(got["prepare_dispatched"])
            self.assertEqual(got["provider_exception_class"],"NOT_RECORDED")

    def test_official_snapshot_is_not_scheduler_snapshot(self):
        with TemporaryDirectory() as td:
            folder=Path(td)
            s,q,n=synthetic_payloads()
            n["quota_snapshot_digest"]=digest(QuotaSnapshot.model_validate(q["snapshot"]))
            write_synthetic(folder,(s,q,n))
            with self.assertRaisesRegex(ValueError,"canonical fail-closed"):
                h.safe_historical_replay(folder)

    def test_altered_scheduler_digest_refused(self):
        with TemporaryDirectory() as td:
            folder=Path(td)
            s,q,n=synthetic_payloads()
            n["quota_snapshot_digest"]="bad-digest"
            write_synthetic(folder,(s,q,n))
            with self.assertRaisesRegex(ValueError,"canonical fail-closed"):
                h.safe_historical_replay(folder)

    def test_prepared_run_marker_refused(self):
        with TemporaryDirectory() as td:
            folder=Path(td)
            s,q,n=synthetic_payloads()
            s["prepare_dispatch_utc"]="2026-10-21T08:14:00Z"
            write_synthetic(folder,(s,q,n))
            with self.assertRaisesRegex(ValueError,"pre-dispatch"):
                h.safe_historical_replay(folder)

    def test_run_id_marker_refused(self):
        with TemporaryDirectory() as td:
            folder=Path(td)
            s,q,n=synthetic_payloads()
            s["run_id"]="run-already-claimed"
            write_synthetic(folder,(s,q,n))
            with self.assertRaisesRegex(ValueError,"pre-dispatch"):
                h.safe_historical_replay(folder)

    def test_prepared_artifact_refused(self):
        with TemporaryDirectory() as td:
            folder=Path(td)
            write_synthetic(folder)
            (folder/"prepare.json").write_text("{}\n")
            with self.assertRaisesRegex(ValueError,"post-dispatch"):
                h.safe_historical_replay(folder)

    def test_unrelated_quota_failure_reason_refused(self):
        with TemporaryDirectory() as td:
            folder=Path(td)
            s,q,n=synthetic_payloads()
            n["candidates"][0]["eligibility"]["reasons"]=["quota_insufficient"]
            write_synthetic(folder,(s,q,n))
            with self.assertRaisesRegex(ValueError,"quota_unknown"):
                h.safe_historical_replay(folder)

    def test_below_medium_quota_refused(self):
        with TemporaryDirectory() as td:
            folder=Path(td)
            s,q,n=synthetic_payloads()
            q["effective"]["five_hour"]=.09
            write_synthetic(folder,(s,q,n))
            with self.assertRaisesRegex(ValueError,"MEDIUM"):
                h.safe_historical_replay(folder)

    def test_missing_snapshot_refused(self):
        with TemporaryDirectory() as td:
            folder=Path(td)
            folder.mkdir(exist_ok=True)
            with self.assertRaisesRegex(ValueError,"Missing"):
                h.safe_historical_replay(folder)

    def test_symlinked_evidence_refused(self):
        with TemporaryDirectory() as td:
            folder=Path(td)
            write_synthetic(folder)
            target=folder/"quota-before-prepare.json"
            target.unlink()
            target.symlink_to(folder/"prepare-summary.json")
            with self.assertRaisesRegex(ValueError,"symlinked"):
                h.safe_historical_replay(folder)

    def test_parser_never_uses_runtime_subprocess(self):
        with TemporaryDirectory() as td:
            folder=Path(td)
            write_synthetic(folder)
            with patch("subprocess.run",
                       side_effect=AssertionError("No subprocess allowed")):
                self.assertEqual(h.safe_historical_replay(folder)["paid_worker_started"],
                                 False)

    def test_canonical_provider_failure_remains_fail_closed(self):
        provider=Mock()
        provider.get_snapshot.side_effect=ProviderUnavailableError("synthetic-no-rpc")
        with patch.object(resolver,"get_account_quota_provider",
                          return_value="codex_app_server"), (
             patch.object(resolver,"resolve_quota_provider",
                          return_value=provider)):
            fallback=resolver.read_current_quota(
                "synthetic-offline-account",fail_closed=True)
            self.assertEqual(digest(fallback),
                 digest(h.unknown_quota_snapshot("synthetic-offline-account",
                                                 "codex_app_server")))
            with self.assertRaises(ProviderUnavailableError):
                resolver.read_current_quota(
                    "synthetic-offline-account",fail_closed=False)

    def test_quota_error_also_remains_fail_closed(self):
        provider=Mock()
        provider.get_snapshot.side_effect=QuotaError("synthetic-malformed")
        with patch.object(resolver,"get_account_quota_provider",
                          return_value="codex_app_server"), (
             patch.object(resolver,"resolve_quota_provider",
                          return_value=provider)):
            out=resolver.read_current_quota("synthetic",fail_closed=True)
            self.assertEqual(out.observed_at.year,1970)

    def test_unknown_quota_mode_is_conservation(self):
        u=h.unknown_quota_snapshot("synthetic","codex_app_server")
        state=QuotaManager(QuotaPolicy()).state(u,
                                                now=datetime.now(timezone.utc))
        self.assertTrue(state.stale)
        self.assertIsNone(state.five_hour_effective)
        self.assertEqual(state.mode.value,"conservation")

    def test_safe_error_classifier_does_not_echo_provider_text(self):
        for exc in (QuotaError("private token ABC"), ProviderUnavailableError("secret XYZ")):
            summary=h.classify_provider_error(exc)
            self.assertEqual(summary["error_family"],"quota_provider")
            self.assertNotIn(str(exc),json.dumps(summary))
            self.assertTrue(summary["fail_closed"])

    def test_main_replay_mode_no_evidence_write(self):
        with TemporaryDirectory() as td:
            folder=Path(td)
            write_synthetic(folder)
            initial={p.name:p.read_bytes() for p in folder.iterdir()}
            with patch.object(h,"safe_historical_replay",
                              wraps=lambda: h.safe_historical_replay(folder)), (
                 patch.object(sys,"argv",["offline","--replay-attempt1"])), (
                 redirect_stdout(io.StringIO())) as out:
                self.assertEqual(h.main(),0)
            self.assertIn("FALLBACK_REPLAY_PASS",out.getvalue())
            self.assertEqual(initial,{p.name:p.read_bytes() for p in folder.iterdir()})

    def test_no_execute_cli_is_supported(self):
        with patch.object(sys,"argv",["offline","--execute"]), (
             redirect_stderr(io.StringIO())):
            with self.assertRaises(SystemExit) as caught:
                h.main()
        self.assertEqual(caught.exception.code,2)

    def test_preview_uses_no_fresh_quota_or_prepare(self):
        with TemporaryDirectory() as td:
            root=Path(td)
            a1=root/"attempt1"
            a2=root/"attempt2"
            write_synthetic(a1)
            ok={"decision":"D2_CTL_READ_ONLY_PREPARE_GATE_PASS__CLAIM_NOT_AUTHORIZED",
                "ctl_run_count":0, "ctl_worktree_clean":True,
                "beads_task":"open_unclaimed",
                "policy_head":h.POLICY_HEAD,"direct_base":h.BASE}
            binpath=root/"fake-venv"/"bin"
            binpath.mkdir(parents=True)
            (binpath/"python").symlink_to(Path(sys.executable).resolve())
            env={"PROJECTCTL_HOME":str(root/"ctl-home"),
                 "BD_ACTOR":"d2-dogfood-owner"}
            with patch.object(h,"ROOT",root),patch.object(h,"ATTEMPT1",a1), (
                 patch.object(h,"ATTEMPT2",a2)), (
                 patch.object(h,"VENV",binpath.parent)), (
                 patch.dict(h.os.environ,env)), (
                 patch.object(h,"safe_historical_replay",
                              wraps=lambda: h.safe_historical_replay(a1))), (
                 patch.object(h.readiness,"audit",return_value=ok)), (
                 patch("subprocess.run",
                       side_effect=AssertionError("no provider, prepare or worker calls"))):
                out=h.preview_attempt2()
            self.assertEqual(out["decision"],
                 "D2_ATTEMPT2_OFFLINE_PREVIEW_PASS__NO_CLAIM_NO_INFERENCE")
            self.assertFalse(a2.exists())
            self.assertFalse(out["run_prepare_called"])

    def test_preview_refuses_existing_attempt2_identity(self):
        with TemporaryDirectory() as td:
            root=Path(td)
            a2=root/"attempt2"
            a2.mkdir()
            binpath=root/"venv"/"bin"
            binpath.mkdir(parents=True)
            (binpath/"python").symlink_to(Path(sys.executable).resolve())
            with patch.object(h,"ROOT",root),patch.object(h,"ATTEMPT2",a2), (
                 patch.object(h,"VENV",binpath.parent)), (
                 patch.dict(h.os.environ,{"PROJECTCTL_HOME":str(root/"ctl-home"),
                                          "BD_ACTOR":"d2-dogfood-owner"})), (
                 patch.object(h.readiness,"audit",
                     side_effect=AssertionError("must refuse before audit"))):
                with self.assertRaisesRegex(ValueError,"already exists"):
                    h.preview_attempt2()


if __name__=="__main__":
    unittest.main()
