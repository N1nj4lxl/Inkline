from __future__ import annotations

import tkinter as tk
from tkinter import colorchooser


HIGHLIGHT_COLORS = {
    "Yellow": "#fff59d",
    "Green": "#c8e6c9",
    "Blue": "#bbdefb",
    "Pink": "#f8bbd0",
    "Purple": "#e1bee7",
    "Red": "#ffcdd2",
    "Grey": "#e0e0e0",
}


class RichTextController:
    def __init__(self, text: tk.Text):
        self.text = text
        self._configure_tags()

    def _configure_tags(self):
        self.text.tag_configure("bold", font=("TkDefaultFont", 11, "bold"))
        self.text.tag_configure("italic", font=("TkDefaultFont", 11, "italic"))
        self.text.tag_configure("underline", underline=True)
        self.text.tag_configure("strikethrough", overstrike=True)
        self.text.tag_configure("align_left", justify="left")
        self.text.tag_configure("align_center", justify="center")
        self.text.tag_configure("align_right", justify="right")
        sizes = {"h1": 24, "h2": 20, "h3": 16, "h4": 13}
        for tag, size in sizes.items():
            self.text.tag_configure(tag, font=("TkDefaultFont", size, "bold"), spacing1=6, spacing3=2)
        for name, color in HIGHLIGHT_COLORS.items():
            self.text.tag_configure(f"highlight_{name.lower()}", background=color)

    def _selection(self):
        try:
            return self.text.index("sel.first"), self.text.index("sel.last")
        except tk.TclError:
            return None

    def toggle_tag(self, tag: str):
        sel = self._selection()
        if not sel:
            return
        start, end = sel
        if tag in self.text.tag_names("sel.first"):
            self.text.tag_remove(tag, start, end)
        else:
            self.text.tag_add(tag, start, end)

    def apply_header(self, level: int):
        sel = self._selection()
        if not sel:
            return
        start, end = sel
        for t in ("h1", "h2", "h3", "h4"):
            self.text.tag_remove(t, start, end)
        self.text.tag_add(f"h{level}", start, end)

    def apply_highlight(self, name: str):
        sel = self._selection()
        if not sel:
            return
        start, end = sel
        for t in [x for x in self.text.tag_names() if x.startswith("highlight_")]:
            self.text.tag_remove(t, start, end)
        self.text.tag_add(f"highlight_{name.lower()}", start, end)

    def apply_text_color(self, color: str | None = None):
        sel = self._selection()
        if not sel:
            return
        if color is None:
            color = colorchooser.askcolor(title="Text colour")[1]
        if not color:
            return
        tag = f"fg_{color.replace('#', '')}"
        self.text.tag_configure(tag, foreground=color)
        start, end = sel
        for t in self.text.tag_names():
            if t.startswith("fg_"):
                self.text.tag_remove(t, start, end)
        self.text.tag_add(tag, start, end)

    def clear_formatting(self):
        sel = self._selection()
        if not sel:
            return
        start, end = sel
        for t in self.text.tag_names():
            if t != "sel":
                self.text.tag_remove(t, start, end)

    def align(self, mode: str):
        sel = self._selection()
        if not sel:
            return
        start, end = sel
        ls = self.text.index(f"{start} linestart")
        le = self.text.index(f"{end} lineend")
        for t in ("align_left", "align_center", "align_right"):
            self.text.tag_remove(t, ls, le)
        self.text.tag_add(f"align_{mode}", ls, le)

    def insert_list(self, kind: str):
        sel = self._selection()
        if sel:
            start, end = sel
        else:
            start = self.text.index("insert linestart")
            end = self.text.index("insert lineend")
        lines = self.text.get(start, end).splitlines() or [""]
        out = []
        for i, line in enumerate(lines, 1):
            if kind == "bullet": out.append(f"• {line}")
            elif kind == "numbered": out.append(f"{i}. {line}")
            else: out.append(f"☐ {line}")
        self.text.delete(start, end)
        self.text.insert(start, "\n".join(out))
