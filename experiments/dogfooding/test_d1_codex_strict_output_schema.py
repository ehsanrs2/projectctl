"""Offline D1 regression for strict Codex worker structured-output wire schema.

No Codex credentials, API call, turn or Git mutation.
"""
import json
from types import SimpleNamespace
import unittest

from pydantic import ValidationError

from projectctl.schemas.execution import WorkerOutputPayload
from projectctl.workers.codex.adapter import (
    CodexWorkerAdapter,
    _strict_worker_output_schema,
)


VALID = {
    "status": "implemented",
    "summary": "Implemented the fixture without changing protected files.",
    "blockers": [],
    "requested_permissions": [],
    "suggested_verification": ["python3 -B -m unittest -v test_user_id.py"],
}


def object_nodes(node):
    if isinstance(node, dict):
        if node.get("type") == "object":
            yield node
        for value in node.values():
            yield from object_nodes(value)
    elif isinstance(node, list):
        for value in node:
            yield from object_nodes(value)


def keys_in(node, found):
    if isinstance(node, dict):
        found.update(node)
        for child in node.values():
            keys_in(child, found)
    elif isinstance(node, list):
        for child in node:
            keys_in(child, found)


class D1CodexStrictOutputSchemaTests(unittest.TestCase):
    def test_default_pydantic_schema_is_not_strict_provider_schema(self):
        original = WorkerOutputPayload.model_json_schema()
        self.assertIn("blockers", original["properties"])
        self.assertNotIn("blockers", original["required"])

    def test_wire_schema_requires_every_root_property(self):
        output = _strict_worker_output_schema()
        self.assertEqual(set(output["properties"]), set(WorkerOutputPayload.model_fields))
        self.assertEqual(set(output["required"]), set(output["properties"]))
        self.assertEqual(
            set(output["required"]),
            {"status", "summary", "blockers", "requested_permissions", "suggested_verification"},
        )
        self.assertEqual(output["type"], "object")
        self.assertIs(output["additionalProperties"], False)

    def test_nested_permission_object_is_strict_too(self):
        output = _strict_worker_output_schema()
        nodes = list(object_nodes(output))
        self.assertEqual(len(nodes), 2)
        for node in nodes:
            self.assertEqual(set(node["properties"]), set(node["required"]))
            self.assertIs(node["additionalProperties"], False)
        self.assertEqual(set(output["$defs"]["PermissionRequest"]["required"]),
                         {"capability", "reason"})

    def test_remove_defaults_and_wire_only_string_constraints(self):
        output = _strict_worker_output_schema()
        names = set()
        keys_in(output, names)
        self.assertNotIn("default", names)
        self.assertNotIn("minLength", names)
        json.dumps(output)

    def test_both_worker_start_and_resume_use_strict_schema(self):
        dummy_request = SimpleNamespace(worker=SimpleNamespace(actual_model="gpt-6-luna"))
        kwargs = CodexWorkerAdapter._turn_kwargs(
            dummy_request, approval="deny_all", sandbox="workspace_write"
        )
        self.assertEqual(kwargs["output_schema"], _strict_worker_output_schema())
        self.assertEqual(kwargs["model"], "gpt-6-luna")

    def test_valid_implemented_and_blocked_responses_still_parse(self):
        implemented = WorkerOutputPayload.model_validate(VALID)
        self.assertEqual(implemented.status.value, "implemented")
        blocked = WorkerOutputPayload.model_validate({
            "status": "blocked",
            "summary": "Blocked by an explicit decision.",
            "blockers": ["needs owner decision"],
            "requested_permissions": [{"capability": "network", "reason": "not approved"}],
            "suggested_verification": [],
        })
        self.assertEqual(blocked.requested_permissions[0].capability, "network")

    def test_internal_defaults_preserved_for_existing_reader(self):
        minimal = WorkerOutputPayload.model_validate({
            "status": "implemented", "summary": "done"
        })
        self.assertEqual(minimal.blockers, [])
        self.assertEqual(minimal.requested_permissions, [])
        self.assertEqual(minimal.suggested_verification, [])

    def test_semantic_validation_still_rejects_empty_summary_and_bad_permission(self):
        with self.assertRaises(ValidationError):
            WorkerOutputPayload.model_validate({**VALID, "summary": ""})
        with self.assertRaises(ValidationError):
            WorkerOutputPayload.model_validate({
                **VALID,
                "requested_permissions": [{"capability": "", "reason": "invalid"}],
            })

    def test_extra_result_fields_remain_forbidden(self):
        with self.assertRaises(ValidationError):
            WorkerOutputPayload.model_validate({**VALID, "unapproved": True})


if __name__ == "__main__":
    unittest.main()
