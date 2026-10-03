from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from projectctl.core.digest import digest
from projectctl.core.errors import VerificationError
from projectctl.schemas.verification import (
    VerificationCatalog,
    VerificationCommand,
    VerificationProfile,
)

CATALOG_PATH = "projectctl.verification.yaml"


@dataclass(frozen=True)
class ResolvedVerificationProfile:
    profile: VerificationProfile
    profile_digest: str
    source: str


def _builtin_profile(project_root: Path) -> ResolvedVerificationProfile:
    commands: list[VerificationCommand] = []
    sources: list[str] = []

    if (project_root / "pyproject.toml").is_file() and (project_root / "tests").is_dir():
        sources.append("pyproject.toml+tests")
        commands.append(
            VerificationCommand(
                id="pytest",
                argv=["python", "-m", "pytest", "-q"],
                timeout_seconds=1200,
            )
        )

    package_json = project_root / "package.json"
    if package_json.is_file():
        try:
            package = json.loads(package_json.read_text(encoding="utf-8"))
        except Exception as exc:
            raise VerificationError(f"Invalid package.json while resolving verification: {exc}") from exc
        scripts = package.get("scripts") if isinstance(package, dict) else None
        if isinstance(scripts, dict) and scripts.get("test"):
            sources.append("package.json")
            commands.append(
                VerificationCommand(
                    id="npm-test",
                    argv=["npm", "test"],
                    timeout_seconds=1200,
                )
            )

    if (project_root / "go.mod").is_file():
        sources.append("go.mod")
        commands.append(
            VerificationCommand(
                id="go-test",
                argv=["go", "test", "./..."],
                timeout_seconds=1200,
            )
        )

    if (project_root / "Cargo.toml").is_file():
        sources.append("Cargo.toml")
        commands.append(
            VerificationCommand(
                id="cargo-test",
                argv=["cargo", "test"],
                timeout_seconds=1800,
            )
        )

    if not commands:
        raise VerificationError(
            "No verification catalog is configured and no deterministic built-in "
            "profile could be inferred. Create projectctl.verification.yaml."
        )

    profile = VerificationProfile(id="default", commands=commands)
    return ResolvedVerificationProfile(
        profile=profile,
        profile_digest=digest(profile),
        source="builtin:" + ",".join(sorted(set(sources))),
    )


def resolve_verification_profile(
    project_root: Path,
    profile_id: str = "default",
) -> ResolvedVerificationProfile:
    path = project_root / CATALOG_PATH
    if not path.exists():
        if profile_id != "default":
            raise VerificationError(
                f"Verification profile {profile_id!r} requires {CATALOG_PATH}."
            )
        return _builtin_profile(project_root)

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise VerificationError(f"{CATALOG_PATH} must be a YAML mapping.")
        catalog = VerificationCatalog.model_validate(raw)
    except (yaml.YAMLError, ValidationError) as exc:
        raise VerificationError(f"Invalid {CATALOG_PATH}: {exc}") from exc

    selected = profile_id or catalog.default_profile
    if selected == "default" and selected not in catalog.profiles:
        selected = catalog.default_profile
    profile = catalog.profiles.get(selected)
    if profile is None:
        raise VerificationError(
            f"Unknown verification profile {selected!r}; available: "
            + ", ".join(sorted(catalog.profiles))
        )
    return ResolvedVerificationProfile(
        profile=profile,
        profile_digest=digest(profile),
        source=CATALOG_PATH,
    )
