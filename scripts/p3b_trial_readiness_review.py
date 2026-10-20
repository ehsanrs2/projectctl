"""M6.0 P3b — offline, nonauthorizing review of untrusted P3a JSON.

No filesystem inspection, service changes, credentials, source data or trial
execution. Parsing a valid observation NEVER promotes any operational gate.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

_DECISION = "P3B_NO_GO_TRIAL_UNAUTHORIZED"
_REFUSAL = "P3B_REVIEW_REFUSED"
_MAX_INPUT_BYTES = 16384
_UNKNOWN = frozenset({
    "OWNER_AND_CODE_ORIGIN_NOT_PROVEN",
    "INHERITED_FD_AND_GROUP_BYPASS_NOT_TESTED",
    "MOUNT_ALIASES_AND_NAMESPACE_NOT_VERIFIED",
    "ACL_AND_DAC_ARE_NOT_ENFORCEMENT_TESTS",
    "NO_INDEPENDENT_CREDENTIAL",
    "NO_DURABLE_COMMIT_OR_ANTIROLLBACK",
    "NO_SOURCE_EPOCH_OR_PRODUCER_AUTHENTICATION",
    "NO_REBOOT_TEST",
})
_AUTH_KEYS = frozenset({
    "provision_custodian", "real_db_access", "trial_with_privileges",
    "trusted_source_export", "worker_task_expansion", "writer_reader_collector_cli",
})
_EXPECTED_KEYS = frozenset({
    "schema_kind", "schema_version", "classification", "decision", "candidate",
    "process", "platform", "ancestry", "mount", "unknowns", "authorization",
})
_ROW_KEYS = frozenset({
    "position", "owner_is_effective_uid", "group_matches_process",
    "owner_write_bit", "group_write_bit", "other_write_bit",
    "sticky_bit", "acl",
})
_CANDIDATE_KEYS = frozenset({"depth", "existing_directory", "path_disclosed"})
_PROCESS_KEYS = frozenset({
    "effective_uid", "effective_gid", "supplementary_group_count",
    "effective_capabilities",
})
_PLATFORM_KEYS = frozenset({"os", "kernel_release"})
_MOUNT_KEYS = frozenset({"filesystem_type", "mount_readonly_observed"})
_FALSE_AUTH = {
    "privileged_disposable_trial": False,
    "provision_custodian": False,
    "deploy_custodian": False,
    "source_db_or_wal": False,
    "enable_w1_r1_collector_cli": False,
    "migration_v3": False,
    "worker_task_expansion": False,
}


class P3bRefusal(ValueError):
    """Fixed error without input data or filesystem paths."""


def _refuse() -> None:
    raise P3bRefusal(_REFUSAL)


def _fields(obj: object, fields: frozenset[str]) -> dict:
    if type(obj) is not dict or obj.keys() != fields:
        _refuse()
    return obj


def _int(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _bool(value: object) -> bool:
    return type(value) is bool


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict:
    result: dict = {}
    for k, v in pairs:
        if k in result:
            _refuse()
        result[k] = v
    return result


def parse_p3a_bytes(raw: bytes) -> dict:
    """Bounded decoding; failures emit no caller-controlled bytes."""
    if type(raw) is not bytes or not raw or len(raw) > _MAX_INPUT_BYTES:
        _refuse()
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"),
                           object_pairs_hook=_pairs_no_duplicates,
                           parse_constant=lambda _: _refuse())
    except (ValueError, UnicodeError, RecursionError):
        _refuse()
    return _fields(value, _EXPECTED_KEYS)


def review_inventory(value: object) -> dict:
    """Validate a P3a shape and issue ONLY an offline NO-GO finding."""
    p = _fields(value, _EXPECTED_KEYS)
    if (p["schema_kind"] != "projectctl.m6_0.p3a.nonprivileged_inventory"
            or not _int(p["schema_version"], 1, 1)
            or p["classification"] != "UNTRUSTED_READ_ONLY_OBSERVATION"
            or p["decision"] != "P3A_INVENTORY_ONLY_NO_GO"):
        _refuse()
    cand = _fields(p["candidate"], _CANDIDATE_KEYS)
    if (not _int(cand["depth"], 1, 32)
            or cand["existing_directory"] is not True
            or cand["path_disclosed"] is not False):
        _refuse()
    proc = _fields(p["process"], _PROCESS_KEYS)
    if (not _int(proc["effective_uid"], 1, 2**32 - 1)
            or not _int(proc["effective_gid"], 1, 2**32 - 1)
            or not _int(proc["supplementary_group_count"], 0, 4096)
            or proc["effective_capabilities"] not in
            ("NONE_OBSERVED", "PRESENT", "UNKNOWN")):
        _refuse()
    plat = _fields(p["platform"], _PLATFORM_KEYS)
    if (plat["os"] != "Linux"
            or type(plat["kernel_release"]) is not str
            or re.fullmatch(r"[A-Za-z0-9._+~\-]{1,128}", plat["kernel_release"]) is None):
        _refuse()
    mount = _fields(p["mount"], _MOUNT_KEYS)
    fs = mount["filesystem_type"]
    if (type(fs) is not str or re.fullmatch(r"[A-Za-z0-9._+\-]{1,40}", fs) is None
            or mount["mount_readonly_observed"] not in (True, False, None)
            or (mount["mount_readonly_observed"] is not None
                and not _bool(mount["mount_readonly_observed"]))):
        _refuse()
    rows = p["ancestry"]
    if type(rows) is not list or len(rows) != cand["depth"] + 1:
        _refuse()
    for idx, row in enumerate(rows):
        r = _fields(row, _ROW_KEYS)
        if r["position"] != ("candidate" if idx == len(rows) - 1 else "ancestor"):
            _refuse()
        if any(not _bool(r[key]) for key in (
            "owner_is_effective_uid", "group_matches_process", "owner_write_bit",
            "group_write_bit", "other_write_bit", "sticky_bit",
        )) or r["acl"] not in ("ACL_XATTR_PRESENT", "ACL_XATTR_NOT_SEEN", "UNKNOWN"):
            _refuse()
    unknowns = p["unknowns"]
    if (type(unknowns) is not list or len(unknowns) != len(_UNKNOWN)
            or any(type(s) is not str for s in unknowns)
            or set(unknowns) != _UNKNOWN):
        _refuse()
    auth = _fields(p["authorization"], _AUTH_KEYS)
    if any(auth[k] is not False for k in _AUTH_KEYS):
        _refuse()

    blockers = [
        "UNATTESTED_SELF_OBSERVATION_NOT_SECURITY_PROOF",
        "NO_INDEPENDENT_PRINCIPAL_OR_LEGACY_WRITER_DENIAL",
        "NO_SINGLE_DURABLE_COMMIT_AND_RESTART_WITNESS",
        "NO_PROTECTED_REPLAY_HIGH_WATER_OR_ROLLBACK_WITNESS",
        "NO_AUTHENTICATED_PRODUCER_OR_SOURCE_EPOCH",
        "NO_OWNER_APPROVED_DISPOSABLE_TOPOLOGY_OR_PRIVILEGED_SCOPE",
        "NO_INDEPENDENT_REVIEW_OF_P3_F01_TO_F28",
    ]
    target = "PERSISTENCE_UNVERIFIED"
    if fs in {"tmpfs", "ramfs", "devtmpfs"}:
        target = "VOLATILE_FS_REJECT_FOR_DURABLE_CUSTODY"
        blockers.append("VOLATILE_STORAGE_OBSERVED")
    if rows[-1]["other_write_bit"] or rows[-1]["group_write_bit"]:
        blockers.append("SHARED_WRITABLE_CANDIDATE_OBSERVED")
    if rows[-1]["sticky_bit"]:
        blockers.append("STICKY_BIT_IS_NOT_CUSTODY_BOUNDARY")
    if proc["effective_capabilities"] != "NONE_OBSERVED":
        blockers.append("CALLER_EFFECTIVE_CAPABILITIES_NOT_ZERO_CONFIRMED")
    return {
        "schema_kind": "projectctl.m6_0.p3b.trial_readiness_review",
        "schema_version": 1,
        "classification": "UNTRUSTED_OFFLINE_REVIEW_NOT_ATTESTATION",
        "decision": _DECISION,
        "target_assessment": target,
        "blockers": blockers,
        "authorizations": dict(_FALSE_AUTH),
        "safe_to_retry_or_auto_promote": False,
    }


def main() -> int:
    """Accept only stdin, emit bounded redacted JSON; never write to disk."""
    if os.getuid() == 0 or os.geteuid() == 0 or os.getuid() != os.geteuid():
        print(_REFUSAL, file=sys.stderr)
        return 2
    try:
        raw = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)
        result = review_inventory(parse_p3a_bytes(raw))
    except (P3bRefusal, OSError):
        print(_REFUSAL, file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
