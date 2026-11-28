#!/usr/bin/env python3
"""G14-P0: temporary VM synthetic-only ext4 extraction feasibility.

Standalone Python 3.9+; no project imports, installation, mount, block
device, host operations, credentials, privilege changes or network calls.
All writes are to a new private TemporaryDirectory, even if the disposable
VM starts with a root shell. Not a source importer or a G14 qualification.
"""
import ctypes
import hashlib
import json
import os
import platform
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from contextlib import closing

ACK = "--synthetic-only"
SIZE = 64 * 1024 * 1024
DB = "state.sqlite"
CONTEXT = "context-manifest.json"
DECISION = "G14_P0_FEASIBILITY_ONLY_SOURCE_NOT_ADMITTED"


def capabilities():
    caps = {
        "kernel": platform.release(),
        "arch": platform.machine(),
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "sqlite_deserialize": hasattr(sqlite3.Connection, "deserialize"),
        "root_shell": os.geteuid() == 0,
        "o_noatime": hasattr(os, "O_NOATIME"),
        "dev_kvm_present": Path("/dev/kvm").exists(),
        "landlock_abi": None,
        "landlock_errno": None,
        "libseccomp_available": False,
    }
    try:
        ctypes.CDLL("libseccomp.so.2")
        caps["libseccomp_available"] = True
    except OSError:
        pass
    if platform.machine() == "x86_64" and ctypes.sizeof(ctypes.c_void_p) == 8:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.syscall.restype = ctypes.c_long
        result = libc.syscall(ctypes.c_long(444), ctypes.c_void_p(),
                              ctypes.c_size_t(0), ctypes.c_uint(1))
        if result >= 0:
            caps["landlock_abi"] = result
        else:
            caps["landlock_errno"] = ctypes.get_errno()
    return caps


def tool(command, args, cwd, timeout=30):
    # Fixed local binaries; no shell, user-supplied path, or source argument.
    return subprocess.run(
        [command] + args, cwd=str(cwd), timeout=timeout,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C",
             "HOME": str(cwd)},
        check=False,
    )


def image_sample(path):
    # Never silently fall back to an atime-changing observer read.
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NOATIME
                 | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size != SIZE or before.st_nlink != 1:
            raise RuntimeError("UNEXPECTED_IMAGE_IDENTITY")
        h = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > SIZE:
                raise RuntimeError("IMAGE_BOUND_EXCEEDED")
            h.update(chunk)
        after = os.fstat(fd)
        def identity(st):
            return [st.st_dev, st.st_ino, st.st_mode, st.st_nlink,
                    st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_atime_ns]
        if total != SIZE or identity(before) != identity(after):
            raise RuntimeError("OBSERVER_SAMPLE_CHANGED")
        if identity(path.lstat()) != identity(before):
            raise RuntimeError("IMAGE_PATH_CHANGED")
        return {"sha256": h.hexdigest(), "identity": identity(before)}
    finally:
        os.close(fd)


def run_probe(report):
    tools = {name: shutil.which(name, path="/usr/sbin:/usr/bin:/sbin:/bin")
             for name in ("mke2fs", "debugfs")}
    report["tools_present"] = {name: path is not None for name, path in tools.items()}
    if not all(tools.values()):
        report["status"] = "UNAVAILABLE_MISSING_TOOLS"
        return 2
    if not all(hasattr(os, x) for x in ("O_NOATIME", "O_NOFOLLOW", "O_CLOEXEC")):
        report["status"] = "UNAVAILABLE_NO_NOATIME"
        return 2
    with tempfile.TemporaryDirectory(prefix="projectctl-g14-p0-") as directory:
        root = Path(directory)
        tree = root / "tree"
        leaf_dir = tree / "fixture"
        leaf_dir.mkdir(parents=True, mode=0o700)
        # Deliberately minimal surrogate, NOT the ProjectCTL runtime schema.
        db = leaf_dir / DB
        with closing(sqlite3.connect(str(db))) as conn:
            if conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0] != "delete":
                raise RuntimeError("ROLLBACK_MODE_NOT_OBSERVED")
            conn.execute("CREATE TABLE fixture(id INTEGER PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO fixture VALUES (1, 'G14_SYNTHETIC')")
            conn.commit()
        ctx = leaf_dir / CONTEXT
        ctx.write_bytes(b'{"fixture":"G14_SYNTHETIC","schema_version":1}\n')
        expected_db, expected_ctx = db.read_bytes(), ctx.read_bytes()
        if expected_db[18:20] != b"\x01\x01":
            raise RuntimeError("ROLLBACK_HEADER_NOT_OBSERVED")
        if any((leaf_dir / (DB + suffix)).exists()
               for suffix in ("-wal", "-shm", "-journal")):
            raise RuntimeError("UNEXPECTED_SQLITE_SIDECAR")

        image = root / "fixture.raw"
        # Create exactly one fresh regular file. No caller path or device.
        with image.open("xb") as handle:
            handle.truncate(SIZE)
        for name, path in tools.items():
            v = tool(path, ["-V"], root, timeout=5)
            first = (v.stderr + v.stdout).decode("ascii", "replace").splitlines()
            report[name + "_version"] = first[0][:160] if first else "UNKNOWN"
        made = tool(tools["mke2fs"], ["-q", "-t", "ext4", "-F", "-d",
                    "tree", "fixture.raw"], root, timeout=60)
        if made.returncode:
            raise RuntimeError("IMAGE_CREATION_FAILED")
        os.chmod(str(image), 0o400)
        # Known old atime reveals whether debugfs itself alters host metadata.
        # This is intentional preparation, strictly BEFORE the observation cut.
        st = image.stat()
        os.utime(str(image), ns=(1500000000000000000, st.st_mtime_ns))
        before = image_sample(image)
        stats = tool(tools["debugfs"], ["-R", "stats", "fixture.raw"], root)
        if stats.returncode or not any(
            line.strip().lower() == b"filesystem state:         clean"
            or (line.lower().startswith(b"filesystem state:") and
                line.split(b":", 1)[1].strip().lower() == b"clean")
            for line in stats.stdout.splitlines()
        ):
            raise RuntimeError("CLEAN_EXT4_STATE_NOT_OBSERVED")
        # No -w, no mount/loop, and fixed leaf paths in our own image.
        for filename, target in ((DB, "extracted.sqlite"),
                                 (CONTEXT, "extracted.json")):
            result = tool(tools["debugfs"], ["-R",
                "dump /fixture/" + filename + " " + target, "fixture.raw"], root)
            if result.returncode or not (root / target).is_file():
                raise RuntimeError("FIXED_LEAF_EXTRACTION_FAILED")
        after = image_sample(image)
        report["image_bytes_equal"] = before["sha256"] == after["sha256"]
        report["image_identity_and_non_atime_metadata_equal"] = (
            before["identity"][:-1] == after["identity"][:-1])
        report["host_image_atime_changed"] = (
            before["identity"][-1] != after["identity"][-1])
        report["image_atime_before_ns"] = before["identity"][-1]
        report["image_atime_after_ns"] = after["identity"][-1]
        report["db_exact_bytes"] = (root / "extracted.sqlite").read_bytes() == expected_db
        report["context_exact_bytes"] = (root / "extracted.json").read_bytes() == expected_ctx
        # Interpretation only on the extracted copy, never the source image.
        with closing(sqlite3.connect((root / "extracted.sqlite").as_uri() + "?mode=ro",
                                     uri=True)) as conn:
            report["rollback_row_preserved"] = (
                conn.execute("SELECT id,value FROM fixture").fetchall()
                == [(1, "G14_SYNTHETIC")])
            report["sqlite_integrity_ok"] = (
                conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)])
        if not all(report[key] for key in (
            "image_bytes_equal", "image_identity_and_non_atime_metadata_equal",
            "db_exact_bytes", "context_exact_bytes", "rollback_row_preserved",
            "sqlite_integrity_ok",
        )):
            report["status"] = "REFUSED_OBSERVED_MISMATCH"
            return 2
        report["status"] = ("EXTRACTION_OK_HOST_ATIME_CHANGED"
                            if report["host_image_atime_changed"]
                            else "EXTRACTION_OK_SAMPLED_METADATA_EQUAL")
        return 0


def main():
    if sys.argv[1:] != [ACK]:
        print("G14_P0_EXACT_SYNTHETIC_ACK_REQUIRED", file=sys.stderr)
        return 2
    if not sys.platform.startswith("linux") or sys.version_info < (3, 9):
        print("G14_P0_UNSUPPORTED_PLATFORM", file=sys.stderr)
        return 2
    report = {
        "decision": DECISION, "fixture": "SYNTHETIC_SURROGATE_ONLY",
        "source_admitted": False, "independent_observer_proven": False,
        "continuous_nonmutation_proven": False, "g2_g4_executed": False,
        "authorizes_export_cli": False, "authorizes_real_source": False,
    }
    rc = 2
    try:
        report["capabilities"] = capabilities()
        rc = run_probe(report)
    except RuntimeError as exc:
        # Only known fixed codes raised by this script.
        report["status"] = str(exc)
    except (OSError, sqlite3.Error, subprocess.SubprocessError, ValueError):
        report["status"] = "PROBE_FAILED_OR_UNAVAILABLE"
    print("G14_P0_REPORT_BEGIN")
    print(json.dumps(report, sort_keys=True, indent=2))
    print("G14_P0_REPORT_END")
    return rc


if __name__ == "__main__":
    sys.exit(main())
