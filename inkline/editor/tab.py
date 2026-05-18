from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class EditorTab:
    title: str = "Untitled"
    path: str | None = None
    content: str = ""
    dirty: bool = False
    readonly: bool = False
    cursor: str = "1.0"
    zoom: int = 100
    favorites: bool = False
    tags: list[str] = field(default_factory=list)
    mode: str = "Plain Text"
