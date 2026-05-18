from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def build_toolbar(parent: tk.Widget, actions: dict) -> tk.Frame:
    bar = tk.Frame(parent)
    mk = lambda txt, cmd: tk.Button(bar, text=txt, width=3, command=cmd).pack(side=tk.LEFT, padx=1)
    mk("B", actions["bold"])
    mk("I", actions["italic"])
    mk("U", actions["underline"])
    mk("S", actions["strike"])
    tk.Menubutton(bar, text="Highlight", relief=tk.RAISED, direction="below").pack(side=tk.LEFT, padx=2)
    hb = bar.winfo_children()[-1]
    hm = tk.Menu(hb, tearoff=0)
    for color in actions["highlights"]:
        hm.add_command(label=color, command=lambda c=color: actions["highlight"](c))
    hb.configure(menu=hm)
    tk.Button(bar, text="Text Colour", command=actions["text_color"]).pack(side=tk.LEFT, padx=2)
    headers = ttk.Combobox(bar, values=["Header 1", "Header 2", "Header 3", "Header 4"], width=10, state="readonly")
    headers.set("Header")
    headers.pack(side=tk.LEFT, padx=2)
    headers.bind("<<ComboboxSelected>>", lambda *_: actions["header"](int(headers.get().split()[-1])))
    tk.Button(bar, text="Clear", command=actions["clear"]).pack(side=tk.LEFT, padx=2)
    tk.Button(bar, text="•", command=lambda: actions["list"]("bullet")).pack(side=tk.LEFT)
    tk.Button(bar, text="1.", command=lambda: actions["list"]("numbered")).pack(side=tk.LEFT)
    tk.Button(bar, text="☐", command=lambda: actions["list"]("checklist")).pack(side=tk.LEFT)
    tk.Button(bar, text="L", command=lambda: actions["align"]("left")).pack(side=tk.LEFT)
    tk.Button(bar, text="C", command=lambda: actions["align"]("center")).pack(side=tk.LEFT)
    tk.Button(bar, text="R", command=lambda: actions["align"]("right")).pack(side=tk.LEFT)
    return bar
