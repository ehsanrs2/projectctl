class ProjectCtlError(Exception):
    """Base error for expected ProjectCTL failures."""


class ConfigurationError(ProjectCtlError):
    pass


class SchemaError(ProjectCtlError):
    pass


class UnsupportedSchemaVersion(SchemaError):
    pass


class RepositoryContractError(ProjectCtlError):
    pass


class UnsafePathError(ProjectCtlError):
    pass


class AuthorityConflictError(ProjectCtlError):
    pass


class TaskStoreError(ProjectCtlError):
    pass


class TaskImportConflict(ProjectCtlError):
    pass


class ClaimConflictError(TaskStoreError):
    pass


class DigestMismatchError(ProjectCtlError):
    pass


class StaleSnapshotError(ProjectCtlError):
    pass


class QuotaError(ProjectCtlError):
    pass


class QuotaAdmissionError(QuotaError):
    pass


class ProviderUnavailableError(ProjectCtlError):
    pass


class DatabaseVersionError(ProjectCtlError):
    pass


class ProjectLockError(ProjectCtlError):
    pass


class PolicyViolationError(ProjectCtlError):
    pass


class CapabilityError(ProjectCtlError):
    pass


class CapabilityMismatchError(CapabilityError):
    pass


class WorkerError(ProjectCtlError):
    pass


class VerificationError(ProjectCtlError):
    pass


class IntegrationError(ProjectCtlError):
    pass


class RecoveryError(ProjectCtlError):
    pass


class RunStoreError(ProjectCtlError):
    pass


class RunLeaseError(RunStoreError):
    pass


class WorktreeError(ProjectCtlError):
    pass


class InternalProjectCtlError(ProjectCtlError):
    pass
