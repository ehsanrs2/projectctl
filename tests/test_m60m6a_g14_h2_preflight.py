"""G14 P0 synthetic-image smoke, not an actual source qualification."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/m6a_g14_h2_preflight.py"
pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or not hasattr(os, "O_NOATIME")
    or not all(shutil.which(x, path="/usr/sbin:/usr/bin:/sbin:/bin")
               for x in ("mke2fs", "debugfs")),
    reason="G14 P0 synthetic ext4 tools unavailable",
)


def test_fixed_ack_required():
    proc = subprocess.run([sys.executable, "-I", str(SCRIPT)],
                          capture_output=True, timeout=10)
    assert proc.returncode == 2
    assert proc.stdout == b""
    assert b"G14_P0_EXACT_SYNTHETIC_ACK_REQUIRED" in proc.stderr


def test_synthetic_image_roundtrip_reports_only_limited_evidence():
    proc = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--synthetic-only"],
        capture_output=True, timeout=150,
    )
    assert proc.returncode == 0, proc.stdout.decode("utf-8", "replace")
    lines = proc.stdout.decode("utf-8").splitlines()
    assert lines[0] == "G14_P0_REPORT_BEGIN"
    assert lines[-1] == "G14_P0_REPORT_END"
    report = json.loads("\n".join(lines[1:-1]))
    assert report["status"] in (
        "EXTRACTION_OK_HOST_ATIME_CHANGED",
        "EXTRACTION_OK_SAMPLED_METADATA_EQUAL",
    )
    assert all(report[x] for x in (
        "image_bytes_equal", "image_identity_and_non_atime_metadata_equal",
        "db_exact_bytes", "context_exact_bytes", "rollback_row_preserved",
        "sqlite_integrity_ok",
    ))
    assert not any(report[x] for x in (
        "source_admitted", "independent_observer_proven",
        "continuous_nonmutation_proven", "g2_g4_executed",
        "authorizes_export_cli", "authorizes_real_source",
    ))
    assert report["host_image_atime_changed"] == (
        report["image_atime_before_ns"] != report["image_atime_after_ns"])
