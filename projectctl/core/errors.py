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


class DigestMismatchError(ProjectCtlError):
    pass


class StaleSnapshotError(ProjectCtlError):
    pass


class QuotaError(ProjectCtlError):
    pass


class ProviderUnavailableError(ProjectCtlError):
    pass


class DatabaseVersionError(ProjectCtlError):
    pass


class ProjectLockError(ProjectCtlError):
    pass


class InternalProjectCtlError(ProjectCtlError):
    pass
