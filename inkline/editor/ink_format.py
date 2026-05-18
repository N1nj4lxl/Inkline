from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def save_ink_document(path: str, payload: dict) -> None:
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_ink_document(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data


def build_metadata(app_name: str = "Inkline") -> dict:
    return {
        "app": app_name,
        "format": "inkline.richtext.v1",
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
