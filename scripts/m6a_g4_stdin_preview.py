"""M6a G4a: explicit opt-in local offline stdin->stdout preview, LAB_ONLY.

Do not install as projectctl CLI. This module NEVER discovers/opens a source
project path, changes RunStore, or grants an assessment, retry or Worker
authority. Supplying bytes DOES NOT certify their origin, acquisition safety,
coherent DB+JSON epoch or present-day status. Output is locally correlatable.
This standalone research demo does not provide a safe live-RunStore reader.
"""
from __future__ import annotations

import base64
import binascii
import json
import sys

from scripts.m6a_g2_private_byte_diagnostic import G2Refused
from scripts.m6a_g3_private_envelope import (
    G3Refused,
    private_envelope_from_supplied_bytes,
)

_WIRE_MAX = 32 * 1024 * 1024
_DB_MAX = 16 * 1024 * 1024
_ARTIFACT_MAX = 2 * 1024 * 1024
_OUTPUT_MAX = 288 * 1024
_INPUT_FORMAT = "projectctl.m6a-g4a-stdin-input-v0"
_OUTPUT_FORMAT = "projectctl.m6a-g4a-stdout-preview-v0"
_ARTIFACT_KEYS = frozenset({
    "context_manifest", "verification_manifest", "evidence_manifest",
})
_INPUT_KEYS = frozenset({
    "format", "project_id", "run_id", "db_b64", "artifacts_b64",
})
_ACK = "--ack-local-correlatable"


class G4Refused(ValueError):
    """Only fixed reason codes; no user-derived text or path in errors."""


def _unique_keys(items: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in items:
        if key in out:
            raise G4Refused("DUPLICATE_KEY")
        out[key] = value
    return out


def _deny_numbers(_value: str) -> None:
    raise G4Refused("UNSUPPORTED_JSON_NUMBER")


def _decode_b64(value: object, maximum: int, *, optional: bool = False) -> bytes | None:
    if value is None and optional:
        return None
    if type(value) is not str:
        raise G4Refused("INVALID_BASE64_TYPE")
    # Check encoded bound BEFORE allocating a decoded bytes object.
    if not value or len(value) > 4 * ((maximum + 2) // 3):
        raise G4Refused("INVALID_BASE64_LENGTH")
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
        if len(raw) > maximum or base64.b64encode(raw).decode("ascii") != value:
            raise G4Refused("NONCANONICAL_OR_UNBOUNDED_BASE64")
    except (UnicodeError, binascii.Error, ValueError) as exc:
        if isinstance(exc, G4Refused):
            raise
        raise G4Refused("INVALID_BASE64") from None
    return raw


def render_supplied_wire(wire: bytes) -> bytes:
    """Pure bounded transform; no file path, stdout or source IO."""
    if (type(wire) is not bytes or not 2 <= len(wire) <= _WIRE_MAX):
        raise G4Refused("INVALID_OR_UNBOUNDED_WIRE")
    try:
        parsed = json.loads(
            wire.decode("utf-8"), object_pairs_hook=_unique_keys,
            parse_int=_deny_numbers, parse_float=_deny_numbers,
            parse_constant=_deny_numbers,
        )
    except G4Refused:
        raise
    except (ValueError, UnicodeError, RecursionError, TypeError):
        raise G4Refused("INVALID_JSON") from None
    if (type(parsed) is not dict or set(parsed) != _INPUT_KEYS
            or parsed.get("format") != _INPUT_FORMAT
            or type(parsed["project_id"]) is not str
            or type(parsed["run_id"]) is not str):
        raise G4Refused("INVALID_INPUT_CONTRACT")
    encoded_artifacts = parsed["artifacts_b64"]
    if type(encoded_artifacts) is not dict or set(encoded_artifacts) != _ARTIFACT_KEYS:
        raise G4Refused("INVALID_ARTIFACT_CONTRACT")
    db = _decode_b64(parsed["db_b64"], _DB_MAX)
    artifacts = {
        kind: _decode_b64(encoded_artifacts[kind], _ARTIFACT_MAX, optional=True)
        for kind in sorted(_ARTIFACT_KEYS)
    }
    # G2 rejects unsupported SQLite/WAL/version and validates exact historical
    # source formats; G3 requires an assessment-free and nonauthorizing v1 Trace.
    private = private_envelope_from_supplied_bytes(
        db_bytes=db, project_id=parsed["project_id"],
        run_id=parsed["run_id"], artifact_bytes=artifacts,
    )
    if type(private) is not bytes or len(private) > _OUTPUT_MAX:
        raise G4Refused("INVALID_G3_RESULT")
    # The G3 private wrapper cannot be printed unchanged: its
    # output_destination=PRIVATE_RETURN_VALUE_ONLY label would be false.
    # Change presentation labels ONLY, never provenance, assessment or Trace.
    envelope = json.loads(private)
    if (envelope.get("private_format") != "projectctl.m6a-g3-private-envelope-v0"
            or envelope.get("output_destination") != "PRIVATE_RETURN_VALUE_ONLY"
            or envelope.get("source_origin") != "UNATTESTED"
            or envelope.get("cross_store_epoch") != "UNATTESTED"
            or envelope.get("source_current") != "UNKNOWN"
            or envelope.get("assessment_authority") != "NONE"
            or envelope.get("authorizes_export_cli") is not False
            or envelope.get("authorizes_retry") is not False):
        raise G4Refused("UNSAFE_PRIVATE_RESULT")
    envelope["private_format"] = _OUTPUT_FORMAT
    envelope["preview_status"] = "M6A_G4_PREVIEW_LAB_ONLY"
    envelope["output_destination"] = "EXPLICIT_OPT_IN_STDOUT_LAB_ONLY"
    output = (
        json.dumps(envelope, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")
    if len(output) > _OUTPUT_MAX:
        raise G4Refused("INVALID_OUTPUT_BOUND")
    return output


def main(argv: list[str] | None = None) -> int:
    """One exact opt-in arg; all refusals print ZERO bytes to stdout."""
    args = sys.argv[1:] if argv is None else argv
    if args != [_ACK]:
        print("G4_ACK_REQUIRED_OR_UNSUPPORTED_INVOCATION", file=sys.stderr)
        return 2
    if sys.stdin.isatty():
        print("G4_PIPE_REQUIRED", file=sys.stderr)
        return 2
    try:
        wire = sys.stdin.buffer.read(_WIRE_MAX + 1)
        encoded = render_supplied_wire(wire)
    except (G4Refused, G2Refused, G3Refused):
        print("G4_INPUT_REFUSED", file=sys.stderr)
        return 2
    except Exception:
        # Fail with a fixed code. Never leak a traceback containing input.
        print("G4_PREVIEW_UNAVAILABLE", file=sys.stderr)
        return 2
    try:
        written = sys.stdout.buffer.write(encoded)
        if written != len(encoded):
            raise OSError("short_write")
        sys.stdout.buffer.flush()
        return 0
    except (OSError, ValueError):
        # A pipe can close *during* a single write. We cannot roll back bytes
        # delivered to a receiver: output must NEVER be treated as authority.
        print("G4_OUTPUT_REFUSED", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
