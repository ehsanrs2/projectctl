#!/usr/bin/env python3
"""Build one D2 multi-file, frozen-test fixture in a new external local Git repo."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import subprocess
from textwrap import dedent

SOURCE = Path(__file__).resolve().parents[3]
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")

SPEC = """# D2: Offline JSONL activity reporting

Implement exactly three modules: d2events/parse.py, d2events/report.py and
d2events/cli.py, using Python standard library only. Keep every other file
unchanged, including SPEC.md, POLICY.md, d2events/__init__.py and tests/**.

Input: UTF-8 JSON Lines. Every nonblank physical line contains one JSON object
with exactly four string fields: event_id, timestamp, user_id, action.
Ignore blank or whitespace-only lines; physical line numbers are 1-based.
Reject malformed JSON, duplicate JSON object keys, missing/extra keys, values
of wrong type, invalid values and duplicate event IDs (case-sensitive across
all lines). Raise ValueError including the physical line number on error,
without echoing the offending event content or credentials.

event_id must match [A-Za-z0-9-]{1,32}.
user_id is stripped at both ends, must match [A-Za-z0-9_-]{1,32}, and is
canonicalized by ASCII uppercase A-Z -> lowercase a-z only. Internal spaces,
non-ASCII characters and empty strings are invalid user IDs.
timestamp has exact form YYYY-MM-DDTHH:MM:SSZ (20 ASCII characters), a valid
UTC calendar date/time with second in 00..59; do not accept offsets, fractional
seconds, leap seconds, or alternative representations.
action is exactly login, logout or purchase, case-sensitive.

parse_events(lines) in d2events/parse.py takes an iterable of text lines and
returns list[dict[str, str]] with canonical user_id and four original keys.
Even when a later line is invalid, the error must mention its actual physical
line number. Input does not have to be a seekable file.

build_report(events) in d2events/report.py accepts the canonical parsed events
and returns a dictionary:
{"total_events":N,"users":[{"user_id":"id","login":L,"logout":O,
"purchase":P,"first_seen":"YYYY-MM-DDTHH:MM:SSZ",
"last_seen":"YYYY-MM-DDTHH:MM:SSZ"},...]}
Users are sorted by canonical user_id ascending. Counts are nonnegative
integers. first_seen/last_seen are chronologically earliest/latest for each
user even if events arrive out of order. Empty events return
{"total_events":0,"users":[]}.

CLI: python3 -B -m d2events.cli FILE.
Read FILE as UTF-8, parse and aggregate using the two module functions,
and print one newline-terminated compact JSON object to stdout using
sort_keys=True and separators=(",",":"). On malformed input, missing file
or encoding error, exit 1 with a concise stderr diagnostic and no stdout.
On invalid CLI arguments, use argparse exit code 2. Never write to input
or any other file. Never access the network, services, or other repositories.

The worker may inspect but may not modify the tests. Do not commit, merge,
rebase, push or make network requests. Provide only the implementation.
"""

POLICY = """# D2 protected fixture policy

Only d2events/parse.py, d2events/report.py and d2events/cli.py may be changed
by the coding worker. Never modify SPEC.md, POLICY.md, d2events/__init__.py,
tests/**, .gitignore, Git history, ProjectCTL metadata or Beads task data.
All execution is local, network disabled, no shell-based external services.
Independent acceptance: python3 -B -m unittest discover -s tests -p 'test_*.py' -v
"""

PARSER_TESTS = dedent(r'''
import json
import unittest
from d2events.parse import parse_events

def event(event_id="e1", user_id="Alice", timestamp="2026-01-03T10:11:12Z", action="login"):
    return {"event_id":event_id,"timestamp":timestamp,"user_id":user_id,"action":action}

def lines(*items):
    return [json.dumps(x) for x in items]

class ParserTests(unittest.TestCase):
    def test_valid_canonical_event(self):
        got = parse_events(lines(event(user_id="  Alice_9  ")))
        self.assertEqual(got, [event(user_id="alice_9")])

    def test_blank_lines_ignored_physical_number_kept(self):
        self.assertEqual(parse_events([" \n", "\t", *lines(event())]), [event(user_id="alice")])
        with self.assertRaisesRegex(ValueError, r"line 3"):
            parse_events(["\n", "\t", "{bad"])

    def test_empty_input(self):
        self.assertEqual(parse_events([]), [])

    def test_malformed_json_reports_line(self):
        with self.assertRaisesRegex(ValueError, r"line 2"):
            parse_events([*lines(event()), '{"event_id":}'])

    def test_duplicate_json_object_key_rejected(self):
        bad = '{"event_id":"e1","event_id":"e2","timestamp":"2026-01-03T10:11:12Z","user_id":"A","action":"login"}'
        with self.assertRaisesRegex(ValueError, r"line 1"):
            parse_events([bad])

    def test_missing_field(self):
        row = event()
        del row["action"]
        with self.assertRaisesRegex(ValueError, r"line 1"):
            parse_events(lines(row))

    def test_extra_field(self):
        with self.assertRaisesRegex(ValueError, r"line 1"):
            parse_events(lines({**event(), "extra": "x"}))

    def test_all_fields_must_be_strings(self):
        for key in event():
            with self.subTest(field=key):
                with self.assertRaisesRegex(ValueError, r"line 1"):
                    parse_events(lines({**event(), key: None}))

    def test_id_invalid_or_too_long(self):
        for bad in ("", "!", "with space", "e" * 33, "é"):
            with self.subTest(value=bad):
                with self.assertRaisesRegex(ValueError, r"line 1"):
                    parse_events(lines(event(event_id=bad)))

    def test_duplicate_ids_across_lines(self):
        with self.assertRaisesRegex(ValueError, r"line 2"):
            parse_events(lines(event(), event(user_id="Bob")))

    def test_duplicate_ids_case_sensitive(self):
        self.assertEqual(len(parse_events(lines(event(event_id="E1"),event(event_id="e1")))),2)

    def test_user_id_trim_and_ascii_only(self):
        got = parse_events(lines(event(user_id="  AbC-1_z  ")))
        self.assertEqual(got[0]["user_id"], "abc-1_z")
        for bad in ("", "  ", "two words", "é", "x" * 33):
            with self.subTest(value=bad):
                with self.assertRaisesRegex(ValueError, r"line 1"):
                    parse_events(lines(event(user_id=bad)))

    def test_invalid_calendar_date_or_leap_second(self):
        for bad in ("2026-02-30T00:00:00Z","2026-01-01T00:00:60Z","2025-02-29T00:00:00Z"):
            with self.subTest(value=bad):
                with self.assertRaisesRegex(ValueError, r"line 1"):
                    parse_events(lines(event(timestamp=bad)))

    def test_reject_noncanonical_timestamp(self):
        for bad in ("2026-01-01T00:00:00+00:00","2026-01-01T00:00:00.1Z",
                    "2026-1-01T00:00:00Z","2026-01-01 00:00:00Z"):
            with self.subTest(value=bad):
                with self.assertRaisesRegex(ValueError, r"line 1"):
                    parse_events(lines(event(timestamp=bad)))

    def test_action_exact_and_case_sensitive(self):
        for bad in ("LOGIN","delete","","purchase "):
            with self.subTest(value=bad):
                with self.assertRaisesRegex(ValueError, r"line 1"):
                    parse_events(lines(event(action=bad)))

    def test_no_raw_data_leak_from_error(self):
        raw = '{"event_id":"sensitive-value","action":null}'
        with self.assertRaises(ValueError) as ctx:
            parse_events([raw])
        self.assertNotIn("sensitive-value", str(ctx.exception))
''').lstrip("\n")

REPORT_TESTS = dedent(r'''
import unittest
from d2events.parse import parse_events
from d2events.report import build_report
from test_parser import event, lines

class ReportTests(unittest.TestCase):
    def test_empty_report(self):
        self.assertEqual(build_report([]), {"total_events": 0, "users": []})

    def test_user_counts_and_total(self):
        events = parse_events(lines(
            event("e1", "Bob", "2026-01-03T00:00:00Z", "purchase"),
            event("e2", "bob", "2026-01-01T00:00:00Z", "login"),
            event("e3", "BOB", "2026-01-02T00:00:00Z", "logout"),
            event("e4", "bob", "2026-01-04T00:00:00Z", "login")))
        self.assertEqual(build_report(events), {"total_events":4, "users":[{
            "user_id":"bob", "login":2,"logout":1,"purchase":1,
            "first_seen":"2026-01-01T00:00:00Z",
            "last_seen":"2026-01-04T00:00:00Z"
        }]})

    def test_users_sorted_and_timestamps_by_value(self):
        events = parse_events(lines(
            event("e1","Zed","2026-01-03T00:00:00Z","logout"),
            event("e2","Amy","2026-01-08T00:00:00Z","login"),
            event("e3","Amy","2026-01-02T00:00:00Z","purchase")))
        report = build_report(events)
        self.assertEqual(report["total_events"],3)
        self.assertEqual([u["user_id"] for u in report["users"]],["amy","zed"])
        self.assertEqual(report["users"][0]["first_seen"],"2026-01-02T00:00:00Z")
        self.assertEqual(report["users"][0]["last_seen"],"2026-01-08T00:00:00Z")
        self.assertEqual(report["users"][0]["logout"],0)

    def test_different_event_order_same_report(self):
        rows = lines(
            event("e1","B","2026-01-01T00:00:00Z","login"),
            event("e2","A","2026-01-02T00:00:00Z","purchase"),
            event("e3","B","2026-01-03T00:00:00Z","logout"))
        self.assertEqual(build_report(parse_events(rows)),build_report(parse_events(rows[::-1])))
''').lstrip("\n")

CLI_TESTS = dedent(r'''
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from test_parser import event, lines

class CLITests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable,"-B","-m","d2events.cli",*map(str,args)],
                              capture_output=True,text=True,check=False,timeout=15)

    def test_one_line_canonical_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"valid.jsonl"
            path.write_text("\n".join(lines(
                event("e1","Alice","2026-01-03T00:00:00Z","login"),
                event("e2","alice","2026-01-01T00:00:00Z","purchase")))+"\n",encoding="utf-8")
            got = self.run_cli(path)
            expected={"total_events":2,"users":[{"user_id":"alice","login":1,
                  "logout":0,"purchase":1,"first_seen":"2026-01-01T00:00:00Z",
                  "last_seen":"2026-01-03T00:00:00Z"}]}
            self.assertEqual(got.returncode,0,got.stderr)
            self.assertEqual(got.stderr,"")
            self.assertEqual(got.stdout, json.dumps(expected,sort_keys=True,separators=(",",":"))+"\n")

    def test_blank_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"empty.jsonl"
            path.write_text("\n \n\t\n",encoding="utf-8")
            got=self.run_cli(path)
            self.assertEqual(got.returncode,0,got.stderr)
            self.assertEqual(got.stdout,'{"total_events":0,"users":[]}\n')

    def test_invalid_event_exit_one_stderr_only(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"bad.jsonl"
            path.write_text('{"event_id":"SECRET-777","action":"login"}\n',encoding="utf-8")
            got=self.run_cli(path)
            self.assertEqual(got.returncode,1)
            self.assertEqual(got.stdout,"")
            self.assertIn("line 1",got.stderr)
            self.assertNotIn("SECRET-777",got.stderr)

    def test_missing_file_exit_one(self):
        with tempfile.TemporaryDirectory() as folder:
            got=self.run_cli(Path(folder)/"missing.jsonl")
            self.assertEqual(got.returncode,1)
            self.assertEqual(got.stdout,"")
            self.assertTrue(got.stderr.strip())

    def test_invalid_utf8_exit_one(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"bad-encoding.jsonl"
            path.write_bytes(b"\xff\n")
            got=self.run_cli(path)
            self.assertEqual(got.returncode,1)
            self.assertEqual(got.stdout,"")

    def test_wrong_arguments_exit_two(self):
        self.assertEqual(self.run_cli().returncode,2)
        self.assertEqual(self.run_cli("one","two").returncode,2)
''').lstrip("\n")

FILES = {
    ".gitignore": "__pycache__/\n*.py[cod]\n",
    "SPEC.md": SPEC,
    "POLICY.md": POLICY,
    "d2events/__init__.py": '"""Offline activity event utility."""\n',
    "d2events/parse.py": '"""Line-oriented strict parser."""\n\ndef parse_events(lines):\n    raise NotImplementedError\n',
    "d2events/report.py": '"""Per-user event aggregation."""\n\ndef build_report(events):\n    raise NotImplementedError\n',
    "d2events/cli.py": '"""Offline JSONL reporting CLI."""\n\ndef main(argv=None):\n    raise NotImplementedError\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
    "tests/__init__.py": '"""Frozen D2 acceptance tests."""\n',
    "tests/test_parser.py": PARSER_TESTS,
    "tests/test_report.py": REPORT_TESTS,
    "tests/test_cli.py": CLI_TESTS,
}


def validate_output_root(root: Path) -> Path:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("output-root must be an existing real directory, not a symlink")
    canonical = root.resolve()
    if canonical == SOURCE or canonical.is_relative_to(SOURCE) or SOURCE.is_relative_to(canonical):
        raise ValueError("output-root must be outside the research checkout and its ancestors")
    proc = subprocess.run(
        ["git", "-C", str(canonical), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=False, timeout=10)
    if proc.returncode == 0:
        raise ValueError("output-root must not be inside any existing Git worktree")
    return canonical


def build(destination: Path, *, output_root: Path) -> dict[str, str]:
    root = validate_output_root(output_root)
    if destination.parent.resolve() != root or not NAME.fullmatch(destination.name):
        raise ValueError("fixture destination must be one safe leaf below output-root")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("fixture already exists; refusing to overwrite")
    destination.mkdir(mode=0o700)
    for name, data in FILES.items():
        p = destination / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data, encoding="utf-8")

    def git(*args, env=None):
        return subprocess.run(
            ["git", "-C", str(destination), *args],
            capture_output=True, text=True, check=True, timeout=30, env=env,
        ).stdout.strip()

    git("init", "--quiet")
    git("config", "user.name", "D2 Fixture")
    git("config", "user.email", "d2-fixture@invalid.example")
    git("add", "--", *FILES)
    fixed = os.environ.copy()
    fixed.update({
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
    })
    git("commit", "--quiet", "-m", "D2 frozen baseline", env=fixed)
    hashes = {
        "baseline_commit": git("rev-parse", "HEAD"),
        "spec_sha256": hashlib.sha256((destination / "SPEC.md").read_bytes()).hexdigest(),
        "policy_sha256": hashlib.sha256((destination / "POLICY.md").read_bytes()).hexdigest(),
        "tests_tree_sha256": hashlib.sha256(
            b"".join(
                name.encode("utf-8") + b"\0" + (destination / name).read_bytes() + b"\0"
                for name in sorted(FILES) if name.startswith("tests/")
            )
        ).hexdigest(),
    }
    return hashes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="new fixture directory name: ctl or direct")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    if not NAME.fullmatch(args.name):
        parser.error("invalid fixture name")
    destination = validate_output_root(args.output_root) / args.name
    report = build(destination, output_root=args.output_root)
    for key, value in report.items():
        print(f"{key}={value}")
    print(f"fixture={args.name} files={len(FILES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
