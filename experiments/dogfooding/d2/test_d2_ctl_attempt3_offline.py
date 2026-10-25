"""D2 Attempt-3 offline-only synthetic admission and evidence tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from contextlib import redirect_stderr
from experiments.dogfooding.d2 import d2_ctl_attempt3_offline as h


NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def first():
    return {
        "mode": "normal", "stale": False,
        "snapshot": {
            "provider": "codex_app_server", "selected_limit_id": "codex",
            "ordinary_usage_allowed": True, "observed_at": NOW.isoformat(),
            "five_hour": {"remaining_ratio": .85,
                          "source": "official", "confidence": "high"},
            "weekly": {"remaining_ratio": .91,
                       "source": "official", "confidence": "high"},
        },
        "effective": {"five_hour": .70, "weekly": .76},
    }


def scheduler():
    return {
        "evaluated_at": NOW.isoformat(), "quota_mode": "normal",
        "selected_task_id": h.TASK, "quota_snapshot_digest": "independent-2",
        "candidates": [{
            "task_id": h.TASK,
            "eligibility": {"task_id": h.TASK, "eligible": True, "reasons": []},
            "model": {"profile": "balanced", "reasoning": "medium"},
        }],
    }


class FirstQuotaGate(unittest.TestCase):
    def check_blocked(self, value, reason):
        with self.assertRaises(h.AdmissionBlocked) as found:
            h.first_quota_gate(value, now=NOW)
        self.assertEqual(found.exception.code, reason)

    def test_good_snapshot(self):
        self.assertEqual(h.first_quota_gate(first(), now=NOW)["normal"], True)

    def test_conservation_rejected(self):
        q=first();q["mode"]="conservation"
        self.check_blocked(q,"quota_not_normal_or_stale")

    def test_stale_rejected(self):
        q=first();q["stale"]=True
        self.check_blocked(q,"quota_not_normal_or_stale")

    def test_nonofficial_rejected(self):
        q=first();q["snapshot"]["five_hour"]["source"]="unknown"
        self.check_blocked(q,"quota_not_official")

    def test_wrong_provider_rejected(self):
        q=first();q["snapshot"]["provider"]="manual"
        self.check_blocked(q,"quota_authority_invalid")

    def test_unavailable_limit_rejected(self):
        q=first();q["snapshot"]["selected_limit_id"]=None
        self.check_blocked(q,"quota_authority_invalid")

    def test_old_observation_rejected(self):
        q=first();q["snapshot"]["observed_at"]=(NOW-timedelta(seconds=121)).isoformat()
        self.check_blocked(q,"quota_stale")

    def test_naive_observation_rejected(self):
        q=first();q["snapshot"]["observed_at"]="2026-10-25T12:00:00"
        self.check_blocked(q,"timestamp_missing_or_invalid")

    def test_future_observation_rejected(self):
        q=first();q["snapshot"]["observed_at"]=(NOW+timedelta(seconds=11)).isoformat()
        self.check_blocked(q,"quota_stale")

    def test_insufficient_five_hour_rejected(self):
        q=first();q["effective"]["five_hour"]=.17
        self.check_blocked(q,"five_hour_medium_insufficient")

    def test_insufficient_weekly_rejected(self):
        q=first();q["effective"]["weekly"]=.07
        self.check_blocked(q,"weekly_medium_insufficient")

    def test_boolean_ratio_rejected(self):
        q=first();q["effective"]["five_hour"]=True
        self.check_blocked(q,"five_hour_medium_insufficient")

    def test_nonfinite_ratio_rejected(self):
        q=first();q["effective"]["five_hour"]=float("nan")
        self.check_blocked(q,"five_hour_medium_insufficient")

    def test_out_of_range_ratio_rejected(self):
        q=first();q["effective"]["five_hour"]=1.1
        self.check_blocked(q,"five_hour_medium_insufficient")

    def test_missing_bucket_rejected(self):
        q=first();q["snapshot"].pop("weekly")
        self.check_blocked(q,"quota_not_official")


class SchedulerGate(unittest.TestCase):
    def blocked(self, value, reason):
        with self.assertRaises(h.AdmissionBlocked) as found:
            h.scheduler_gate(value, now=NOW, canonical_unknown_digest="unknown")
        self.assertEqual(found.exception.code, reason)

    def test_different_independent_digest_accepted(self):
        self.assertTrue(h.scheduler_gate(scheduler(),now=NOW,
                                        canonical_unknown_digest="unknown")["medium_model"])

    def test_unknown_digest_rejected(self):
        s=scheduler();s["quota_snapshot_digest"]="unknown"
        self.blocked(s,"scheduler_unknown_quota")

    def test_missing_digest_rejected(self):
        s=scheduler();s.pop("quota_snapshot_digest")
        self.blocked(s,"scheduler_unknown_quota")

    def test_conservation_rejected(self):
        s=scheduler();s["quota_mode"]="conservation"
        self.blocked(s,"scheduler_rejected")

    def test_no_selection_rejected(self):
        s=scheduler();s["selected_task_id"]=None
        self.blocked(s,"scheduler_rejected")

    def test_extra_candidate_rejected(self):
        s=scheduler();s["candidates"].append(s["candidates"][0])
        self.blocked(s,"scheduler_candidate_count")

    def test_ineligible_rejected(self):
        s=scheduler();s["candidates"][0]["eligibility"]["reasons"]=["quota_insufficient"]
        self.blocked(s,"scheduler_ineligible")

    def test_mismatched_task_rejected(self):
        s=scheduler();s["candidates"][0]["task_id"]="different"
        self.blocked(s,"scheduler_candidate_drift")

    def test_model_drift_rejected(self):
        s=scheduler();s["candidates"][0]["model"]["reasoning"]="high"
        self.blocked(s,"scheduler_model_drift")

    def test_old_scheduler_decision_rejected(self):
        s=scheduler();s["evaluated_at"]=(NOW-timedelta(seconds=121)).isoformat()
        self.blocked(s,"scheduler_stale")


class OrderingAndHistoricalSafety(unittest.TestCase):
    def test_failed_first_never_queries_scheduler(self):
        q=first();q["effective"]["five_hour"]=.01
        count=[]
        def second():
            count.append("called")
            return scheduler()
        with self.assertRaises(h.AdmissionBlocked):
            h.simulate_ordered_admission(q,second,now=NOW,unknown_digest="unknown")
        self.assertEqual(count,[])

    def test_healthy_first_samples_scheduler_once(self):
        count=[]
        def second():
            count.append("called")
            return scheduler()
        self.assertEqual(
            h.simulate_ordered_admission(first(),second,now=NOW,unknown_digest="unknown")["decision"],
            h.GO)
        self.assertEqual(count,["called"])

    def test_second_unknown_stops_after_one_read(self):
        count=[]
        def second():
            count.append("called")
            s=scheduler();s["quota_snapshot_digest"]="unknown"
            return s
        with self.assertRaises(h.AdmissionBlocked):
            h.simulate_ordered_admission(first(),second,now=NOW,unknown_digest="unknown")
        self.assertEqual(len(count),1)

    def test_second_insufficient_stops_after_one_read(self):
        count=[]
        def second():
            count.append("called")
            s=scheduler();s["quota_mode"]="conservation"
            s["selected_task_id"]=None
            return s
        with self.assertRaises(h.AdmissionBlocked):
            h.simulate_ordered_admission(first(),second,now=NOW,unknown_digest="unknown")
        self.assertEqual(len(count),1)

    def test_evidence_hashing_does_not_write(self):
        with TemporaryDirectory() as td:
            p=Path(td)
            for name in h.ATTEMPT2_FILES:
                (p/name).write_text("{}")
            before={x.name:x.read_bytes() for x in p.iterdir()}
            r=h.evidence_hashes(p)
            self.assertEqual(len(r),3)
            self.assertEqual(before,{x.name:x.read_bytes() for x in p.iterdir()})

    def test_historical_dispatch_marker_rejected(self):
        with TemporaryDirectory() as td:
            p=Path(td)
            for name in h.ATTEMPT2_FILES:
                (p/name).write_text("{}")
            (p/"prepare.json").write_text("{}")
            with self.assertRaisesRegex(h.AdmissionBlocked,"attempt2_dispatch_marker_present"):
                h.evidence_hashes(p)

    def test_historical_symlink_rejected(self):
        with TemporaryDirectory() as td:
            p=Path(td)
            for name in h.ATTEMPT2_FILES:
                (p/name).write_text("{}")
            f=p/h.ATTEMPT2_FILES[0];f.unlink();f.symlink_to(p/h.ATTEMPT2_FILES[1])
            with self.assertRaisesRegex(h.AdmissionBlocked,"attempt2_evidence_invalid"):
                h.evidence_hashes(p)

    def test_preview_refuses_used_identity_without_imports(self):
        with TemporaryDirectory() as td:
            p=Path(td)/"attempt3";p.mkdir()
            with patch.object(h,"ATTEMPT3",p):
                with self.assertRaisesRegex(h.AdmissionBlocked,"identity_already_used"):
                    h.preview(expected_head="a"*40)

    def test_preview_requires_full_reviewed_sha(self):
        with self.assertRaisesRegex(h.AdmissionBlocked,"research_head_invalid"):
            h.preview(expected_head="HEAD")

    def test_cli_rejects_prepare_mode(self):
        with patch.object(sys,"argv",["offline","--prepare","--expected-head","a"*40]), (
                redirect_stderr(io.StringIO())):
            with self.assertRaises(SystemExit) as caught:
                h.main()
        self.assertEqual(caught.exception.code,2)

    def test_preview_guard_has_no_quota_or_prepare_call(self):
        with TemporaryDirectory() as td:
            root=Path(td)
            fake_venv=root/"venv"/"bin";fake_venv.mkdir(parents=True)
            (fake_venv/"python").symlink_to(Path(sys.executable).resolve())
            with patch.object(h,"ATTEMPT3",root/"unused"), (
                    patch.object(h,"ROOT",root)), (
                    patch.object(h,"RESEARCH",root/"research")), (
                    patch.object(h,"VENV",fake_venv.parent)), (
                    patch.dict(h.os.environ,{"PROJECTCTL_HOME":str(root/"ctl-home"),
                                             "BD_ACTOR":"d2-dogfood-owner"})):
                import types
                from unittest.mock import MagicMock
                fake_ready=types.ModuleType("experiments.dogfooding.d2.d2_ctl_readiness")
                fake_ready.git=MagicMock(side_effect=[
                    "research/advisory-skills-eval","a"*40,""])
                fake_ready.audit=MagicMock(return_value={
                    "decision":"D2_CTL_READ_ONLY_PREPARE_GATE_PASS__CLAIM_NOT_AUTHORIZED",
                    "ctl_run_count":0,"beads_task":"open_unclaimed",
                    "ctl_worktree_clean":True,
                    "policy_head":h.POLICY_HEAD,"direct_base":h.DIRECT_BASE})
                with patch.dict(sys.modules,{
                        "experiments.dogfooding.d2.d2_ctl_readiness":fake_ready}), (
                        patch.object(h,"historical_gate",return_value={
                            "attempt1_replay":"pass","attempt2_forensics":"pass",
                            "attempt2_source_sha256":{}})):
                    result=h.preview(expected_head="a"*40)
            self.assertEqual(result["decision"],h.PASS)
            self.assertFalse(result["live_quota_checked"])
            self.assertFalse(result["prepare_dispatched"])
            self.assertFalse(result["attempt3_identity_created"])


if __name__ == "__main__":
    unittest.main()
