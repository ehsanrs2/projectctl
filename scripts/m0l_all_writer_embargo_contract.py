"""M6.0 M0l — pure, intentionally unauthenticated embargo evidence review.

This is a *laboratory* decision contract, NOT enforcement. Claims cannot
authenticate kernel policy, discover unknown writers or authorize migration.
Even all-True observations return LAB_REVIEW_ONLY, never GO.
"""
from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class WriterScopeClaims:
    # Operator-supplied hypotheses, not attestations. Exact bool required.
    source_identity_and_ancestors_anchored: bool = False
    db_wal_shm_and_json_all_covered: bool = False
    symlink_hardlink_mount_aliases_closed: bool = False
    old_writer_processes_and_descendants_drained: bool = False
    inherited_and_preopened_writable_fds_closed: bool = False
    new_independent_same_uid_launches_blocked: bool = False
    systemd_units_timers_sockets_restart_blocked: bool = False
    other_uids_namespaces_and_remote_writers_excluded: bool = False
    embargo_held_through_wal_backup_recovery_release: bool = False
    externally_independent_enforcer_verified: bool = False


@dataclass(frozen=True)
class BypassObservations:
    # None means untested / unknown. False is *only* a reported observation.
    # A reported False cannot ever prove global absence of this class.
    late_writer_wrote: bool | None = None
    preopened_fd_wrote: bool | None = None
    inode_alias_wrote: bool | None = None
    json_outside_db_lock_wrote: bool | None = None


@dataclass(frozen=True)
class LabReview:
    decision: str
    authorizes_migration: bool = False


def review(claims: WriterScopeClaims, bypass: BypassObservations) -> LabReview:
    """Prioritize real bypass observations and fail closed on unknowns.

    NOTE: No outcome from this function grants production admission.
    """
    if type(claims) is not WriterScopeClaims:
        return LabReview("NO_GO_UNSUPPORTED_SCOPE_CLAIMS")
    if type(bypass) is not BypassObservations:
        return LabReview("NO_GO_UNSUPPORTED_BYPASS_OBSERVATIONS")
    for field in fields(bypass):
        observation = getattr(bypass, field.name)
        if observation is True:
            return LabReview("NO_GO_OBSERVED_" + field.name.upper())
        if observation is not False:
            return LabReview("NO_GO_UNVERIFIED_" + field.name.upper())
    for field in fields(claims):
        if getattr(claims, field.name) is not True:
            return LabReview("NO_GO_" + field.name.upper())
    return LabReview("LAB_REVIEW_ONLY")
