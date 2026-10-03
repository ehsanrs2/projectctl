from pathlib import Path

import yaml

from projectctl.schema_export import PUBLIC_SCHEMAS
from projectctl.verification.profile import resolve_verification_profile


def test_verification_contract_versions_are_public():
    expected = {
        "verification-catalog.v1.schema.json",
        "verification-manifest.v1.schema.json",
        "verification-manifest.v2.schema.json",
        "evidence-manifest.v1.schema.json",
        "evidence-manifest.v2.schema.json",
    }
    assert expected <= set(PUBLIC_SCHEMAS)


def test_catalog_profile_is_authoritative(tmp_path: Path):
    catalog = {
        "schema_kind": "projectctl.verification_catalog",
        "schema_version": 1,
        "default_profile": "default",
        "profiles": {
            "default": {
                "id": "default",
                "commands": [
                    {
                        "id": "check",
                        "argv": ["python", "-c", "print('ok')"],
                    }
                ],
            }
        },
    }
    (tmp_path / "projectctl.verification.yaml").write_text(
        yaml.safe_dump(catalog, sort_keys=False),
        encoding="utf-8",
    )
    resolved = resolve_verification_profile(tmp_path)
    assert resolved.source == "projectctl.verification.yaml"
    assert resolved.profile.commands[0].id == "check"
    assert resolved.profile_digest
