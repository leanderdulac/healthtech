"""Compatibilidade entre fhir.resources v7 (R4) e v8 (R5)."""

import json
from typing import Any, Type


def fhir_parse(model_cls: Type, data: dict) -> Any:
    if hasattr(model_cls, "model_validate"):
        return model_cls.model_validate(data)
    return model_cls.parse_obj(data)


def fhir_serialize(resource: Any) -> dict:
    if hasattr(resource, "model_dump"):
        return resource.model_dump(mode="json", exclude_none=True)
    if hasattr(resource, "dict"):
        return json.loads(resource.json(exclude_none=True))
    return dict(resource)