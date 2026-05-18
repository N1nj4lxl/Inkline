from __future__ import annotations

import tkinter as tk


def build_context_menu(root: tk.Widget, actions: dict) -> tk.Menu:
    menu = tk.Menu(root, tearoff=0)
    menu.add_command(label="Bold", command=actions["bold"])
    menu.add_command(label="Italic", command=actions["italic"])
    menu.add_command(label="Underline", command=actions["underline"])
    menu.add_command(label="Strikethrough", command=actions["strike"])
    hm = tk.Menu(menu, tearoff=0)
    for color in actions["highlights"]:
        hm.add_command(label=color, command=lambda c=color: actions["highlight"](c))
    menu.add_cascade(label="Highlight", menu=hm)
    menu.add_command(label="Text Colour", command=actions["text_color"])
    for n in range(1, 5):
        menu.add_command(label=f"Header {n}", command=lambda x=n: actions["header"](x))
    menu.add_separator()
    menu.add_command(label="Clear Formatting", command=actions["clear"])
    return menu
