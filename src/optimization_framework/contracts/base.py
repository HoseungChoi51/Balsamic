"""Canonical JSON identities; independent of storage row IDs and machine paths."""
from __future__ import annotations

import difflib
import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


def canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)
    schema_version: Literal[1] = 1

    def digest(self) -> str:
        return content_hash(self)


def field_names(model) -> set[str]:
    """The keys a model accepts at its top level: its fields' names and aliases."""
    names = set()
    for name, field in model.model_fields.items():
        names.add(name)
        if field.alias:
            names.add(field.alias)
        choices = getattr(field.validation_alias, "choices", None)
        names.update(choice for choice in choices or [field.validation_alias] if isinstance(choice, str))
    return names


def lenient(data: dict, known) -> tuple[dict, list[str]]:
    """An agent's top-level keys (decision 5): the known part and the unknown keys it drops.

    A key close to a known one is refused, so a misspelled field never silently changes what runs. Nested objects stay
    strict: only the top level is split.
    """
    known = sorted(known)
    ignored = [key for key in data if key not in known]
    for key in ignored:
        match = difflib.get_close_matches(key, known, n=1, cutoff=0.8)
        if match:
            raise ValueError(f"Unknown field {key!r}: did you mean {match[0]}?")
    return {key: value for key, value in data.items() if key not in ignored}, ignored
