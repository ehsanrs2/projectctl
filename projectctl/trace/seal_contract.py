"""M6.0 B3a1: PURE internal design contract for a verification as-of seal.

An instance is only structural data, never evidence that a writer committed
an atomic transition or that an exported DB/filesystem snapshot is sound.
No SQLite connection, migrations, file I/O, trusted writer hook or CLI here.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Literal

from pydantic import Field, StrictInt, model_validator

from projectctl.schemas.base import ProjectCtlModel

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z", re.ASCII)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_DIGEST_FIELDS = (
    "run_manifest_raw_sha256",
    "run_record_projection_sha256",
    "verification_manifest_raw_sha256",
    "evidence_manifest_raw_sha256",
)
_MAX_SQLITE_INTEGER = (1 << 63) - 1


class VerificationAsOfSealV1(ProjectCtlModel):
    """Internal, untrusted until bound to one durable writer transaction.

    The fixed shape represents only one non-review success transition:
    VERIFYING -> READY_TO_INTEGRATE. It deliberately includes no verification
    verdict or delivery claim and has no authority-bearing API.
    """

    schema_kind: Literal["projectctl.verification_as_of_seal"]
    schema_version: Literal[1]
    seal_protocol_version: Literal[1]
    artifact_digest_algorithm: Literal["sha256"]

    project_id: str
    run_id: str
    task_id: str
    seal_sequence: StrictInt = Field(ge=1, le=_MAX_SQLITE_INTEGER)
    observed_status: Literal["ready_to_integrate"]
    event_prefix_id: StrictInt = Field(ge=1, le=_MAX_SQLITE_INTEGER)
    run_manifest_schema_version: Literal[2]
    run_manifest_raw_sha256: str
    run_record_projection_sha256: str
    verification_manifest_raw_sha256: str
    evidence_manifest_raw_sha256: str

    @model_validator(mode="before")
    @classmethod
    def validate_exact_unmodified_id_and_digest_fields(cls, value: object) -> object:
        # ProjectCtlModel globally strips whitespace. This pre-check prevents
        # silently turning an altered identity/digest into an acceptable one.
        if isinstance(value, Mapping):
            for key in (
                "schema_version", "seal_protocol_version",
                "run_manifest_schema_version",
            ):
                # Literal[int] alone must not silently admit JSON booleans.
                if type(value.get(key)) is not int:
                    raise ValueError("invalid_seal_version")
            if (
                type(value.get("schema_kind")) is not str
                or value.get("schema_kind") != "projectctl.verification_as_of_seal"
                or type(value.get("artifact_digest_algorithm")) is not str
                or value.get("artifact_digest_algorithm") != "sha256"
                or type(value.get("observed_status")) is not str
                or value.get("observed_status") != "ready_to_integrate"
            ):
                raise ValueError("invalid_seal_kind_or_status")
            for key in ("project_id", "run_id", "task_id"):
                field = value.get(key)
                if type(field) is not str or not _IDENTIFIER.fullmatch(field):
                    raise ValueError("invalid_seal_identity")
            for key in _DIGEST_FIELDS:
                field = value.get(key)
                if type(field) is not str or not _SHA256.fullmatch(field):
                    raise ValueError("invalid_seal_digest")
        return value



_MAX_SEAL_JSON_BYTES = 4096


class _InvalidSealJson(ValueError):
    """Typed internal refusal; never return parser source bytes in an error."""


def _unique_object_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    obj: dict[str, object] = {}
    for name, value in pairs:
        if name in obj:
            raise _InvalidSealJson("duplicate_seal_json_field")
        obj[name] = value
    return obj


def parse_private_seal_json_bytes(data: bytes) -> VerificationAsOfSealV1:
    """Bounded strict decoder; never accepts ambiguous repeated JSON keys."""
    if not isinstance(data, bytes) or len(data) > _MAX_SEAL_JSON_BYTES:
        raise _InvalidSealJson("invalid_seal_json")
    try:
        payload = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_unique_object_fields,
            parse_constant=lambda _x: (_ for _ in ()).throw(_InvalidSealJson(
                "nonfinite_seal_json"
            )),
        )
        if not isinstance(payload, dict):
            raise _InvalidSealJson("invalid_seal_json")
        return VerificationAsOfSealV1.model_validate(payload)
    except _InvalidSealJson:
        raise
    except (ValueError, UnicodeError, TypeError) as _exc:
        raise _InvalidSealJson("invalid_seal_json") from None

def canonical_private_seal_json_bytes(seal: VerificationAsOfSealV1) -> bytes:
    """Deterministic *private* seal serialization; never a public Trace API.

    No dynamic timestamp or arbitrary source fields. The output contains
    project/run/task correlation identifiers, so it must remain local.
    """
    if not isinstance(seal, VerificationAsOfSealV1):
        raise TypeError("expected_private_seal_model")
    return (
        json.dumps(
            seal.model_dump(mode="json"),
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def private_seal_sha256(seal: VerificationAsOfSealV1) -> str:
    """Fingerprint of canonical private seal bytes; NOT an authenticity proof."""
    return hashlib.sha256(canonical_private_seal_json_bytes(seal)).hexdigest()
