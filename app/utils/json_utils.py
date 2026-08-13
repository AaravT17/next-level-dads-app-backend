import json
from typing import Any

def parse_jsonb_value(value: Any, default: Any) -> Any:
    """
    Parse a JSONB value returned as a string, falling back to a default when null.
    """
    if isinstance(value, str):
        return json.loads(value)
    if value is None:
        return default
    return value

def parse_jsonb_fields(row: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize JSONB-backed organization fields for Pydantic response models.
    Parses application answers and internal notes into Python objects.
    """
    row["application_answers"] = parse_jsonb_value(
        row.get("application_answers"), {}
    )

    row["notes"] = parse_jsonb_value(
        row.get("notes"), []
    )

    return row