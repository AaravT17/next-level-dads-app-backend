import json
from typing import Any


def parse_jsonb_fields(row: dict[str, Any]) -> dict[str, Any]:
    application_answers = row.get("application_answers")
    notes = row.get("notes")

    row["application_answers"] = (
        json.loads(application_answers) if isinstance(application_answers, str) else application_answers or {}
    )

    row["notes"] = (
        json.loads(notes) if isinstance(notes, str) else notes or []
    )

    return row