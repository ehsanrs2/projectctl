import hashlib
import json
from typing import Any

from pydantic import BaseModel

DIGEST_ALGORITHM = "canonical-json-sha256-v1"


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=False)
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Stable JSON encoding used by schema generation 1.

    The algorithm identifier is versioned so a future RFC-8785 implementation can
    be introduced through an explicit migration rather than silently changing
    historical fingerprints.
    """
    return json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest(value: Any) -> str:
    h = hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    return f"{DIGEST_ALGORITHM}:{h}"
