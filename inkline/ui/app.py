from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from inkline.config.settings import load_settings, save_settings
from inkline.editor.search_engine import find_matches
from inkline.editor.tab import EditorTab
from inkline.themes.theme_manager import THEMES, ThemeManager
from inkline.utils.file_ops import backup_file, export_file, read_text, write_text
from inkline.editor.ink_format import build_metadata, load_ink_document, save_ink_document
from inkline.editor.rich_text_editor import HIGHLIGHT_COLORS, RichTextController
from inkline.ui.context_menu import build_context_menu
from inkline.ui.formatting_toolbar import build_toolbar
from inkline.utils.text_ops import format_json, reading_time_minutes, remove_double_spaces, trim_empty_lines, word_count
from inkline.workspace.manager import WorkspaceManager


class InklineApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Inkline — Simple notes, sharper tools.")
        self.settings = load_settings()
        self.theme_manager = ThemeManager(self.settings)
        self.workspace = WorkspaceManager(self.settings["workspace_file"])
        self.tabs: dict[str, EditorTab] = {}
        self.recent_files: list[str] = []
        self.quick_notes: list[str] = []
        self.open_folders: list[str] = []
        self._build_ui()
        self._bind_events()
        self._restore_workspace()
        self._schedule_autosave()

    def run(self) -> None:
        self.root.mainloop()

    def _build_ui(self):
        self.root.geometry("1200x760")
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.attributes("-topmost", self.settings["always_on_top"])
        self.root.attributes("-alpha", self.settings["transparent"])
        self._build_menu()
        self.main = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashwidth=3)
        self.main.pack(fill=tk.BOTH, expand=True)
        self.sidebar = tk.Frame(self.main, width=250)
        self.main.add(self.sidebar)
        self.center = tk.Frame(self.main)
        self.main.add(self.center)
        self.toolbar_visible = tk.BooleanVar(value=True)
        self.toolbar_host = tk.Frame(self.center)
        self.toolbar_host.pack(fill=tk.X)
        self.notebook = ttk.Notebook(self.center)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self.status = tk.Label(self.root, anchor="w")
        self.status.pack(fill=tk.X)
        self._build_sidebar()
        self._new_tab()
        self.apply_theme()

    def _build_menu(self):
        menu = tk.Menu(self.root)
        self.root.config(menu=menu)
        f = tk.Menu(menu, tearoff=0); menu.add_cascade(label="File", menu=f)
        f.add_command(label="New", command=self._new_tab)
        f.add_command(label="Open", command=self._open_file)
        f.add_command(label="Open .ink", command=lambda: self._open_file(ink=True))
        f.add_command(label="Save", command=self._save_file)
        f.add_command(label="Save As", command=lambda: self._save_file(save_as=True))
        f.add_command(label="Save as .ink", command=lambda: self._save_file(force_ink=True))
        f.add_command(label="Rename", command=self._rename_current)
        f.add_command(label="Duplicate", command=self._duplicate_current)
        f.add_separator()
        for fmt in ("TXT", "MD", "HTML", "JSON", "PDF"):
            f.add_command(label=f"Export {fmt}", command=lambda x=fmt: self._export(x))
        e = tk.Menu(menu, tearoff=0); menu.add_cascade(label="Edit", menu=e)
        for n,a in [("Undo","<<Undo>>"),("Redo","<<Redo>>"),("Cut","<<Cut>>"),("Copy","<<Copy>>"),("Paste","<<Paste>>")]:
            e.add_command(label=n, command=lambda x=a: self.current_text().event_generate(x))
        e.add_command(label="Paste as Plain Text", command=self._paste_plain)
        e.add_separator()
        e.add_command(label="Mode: Plain Text", command=lambda: self._switch_mode("Plain Text"))
        e.add_command(label="Mode: Rich Text", command=lambda: self._switch_mode("Rich Text"))
        e.add_separator()
        e.add_command(label="Find", command=self._find)
        e.add_command(label="Replace", command=self._replace)
        e.add_command(label="Go To Line", command=self._goto_line)
        e.add_command(label="Format JSON", command=self._format_json)
        e.add_command(label="Remove Double Spaces", command=lambda: self._rewrite(remove_double_spaces))
        e.add_command(label="Trim Empty Lines", command=lambda: self._rewrite(trim_empty_lines))
        v = tk.Menu(menu, tearoff=0); menu.add_cascade(label="View", menu=v)
        v.add_checkbutton(label="Word Wrap", command=self._toggle_wrap)
        v.add_checkbutton(label="Formatting Toolbar", variable=self.toolbar_visible, command=self._toggle_toolbar)
        v.add_checkbutton(label="Focus Mode", command=self._focus_mode)
        v.add_command(label="Zoom In", command=lambda: self._zoom(10))
        v.add_command(label="Zoom Out", command=lambda: self._zoom(-10))
        v.add_checkbutton(label="Always on Top", command=self._toggle_topmost)
        v.add_checkbutton(label="Fullscreen", command=lambda: self.root.attributes("-fullscreen", not self.root.attributes("-fullscreen")))
        t = tk.Menu(menu, tearoff=0); menu.add_cascade(label="Theme", menu=t)
        for name in THEMES:
            t.add_command(label=name, command=lambda n=name: self._set_theme(n))

    def _build_sidebar(self):
        self.sidebar_list = tk.Listbox(self.sidebar)
        self.sidebar_list.pack(fill=tk.BOTH, expand=True)

    def _bind_events(self):
        self.notebook.bind("<<NotebookTabChanged>>", lambda *_: self._update_status())
        self.root.bind("<Control-s>", lambda *_: self._save_file())

    def _text_widget(self):
        frame = tk.Frame(self.notebook)
        nums = tk.Text(frame, width=4, state=tk.DISABLED)
        nums.pack(side=tk.LEFT, fill=tk.Y)
        text = tk.Text(frame, undo=True, wrap=tk.WORD if self.settings["word_wrap"] else tk.NONE)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        text.bind("<KeyRelease>", lambda *_: self._on_change())
        text.bind("<ButtonRelease>", lambda *_: self._update_status())
        text.bind("<Button-3>", self._show_context_menu)
        return frame, text, nums

    def _new_tab(self):
        frame, text, nums = self._text_widget()
        self.notebook.add(frame, text="Untitled")
        tab_id = str(frame)
        frame.text, frame.nums = text, nums
        frame.controller = RichTextController(text)
        frame.context_menu = build_context_menu(self.root, self._actions())
        if not hasattr(self, "toolbar"):
            self.toolbar = build_toolbar(self.toolbar_host, self._actions())
            self.toolbar.pack(fill=tk.X)
        self._bind_rich_shortcuts(text)
        self.tabs[tab_id] = EditorTab()
        self.notebook.select(frame)

    def current_frame(self):
        return self.root.nametowidget(self.notebook.select())

    def current_text(self):
        return self.current_frame().text

    def current_tab(self):
        return self.tabs[str(self.current_frame())]


    def _actions(self):
        c = self.current_frame().controller
        return {
            "bold": lambda: c.toggle_tag("bold"), "italic": lambda: c.toggle_tag("italic"), "underline": lambda: c.toggle_tag("underline"),
            "strike": lambda: c.toggle_tag("strikethrough"), "highlight": c.apply_highlight, "highlights": list(HIGHLIGHT_COLORS.keys()),
            "text_color": c.apply_text_color, "header": c.apply_header, "clear": c.clear_formatting,
            "list": c.insert_list, "align": c.align,
        }

    def _bind_rich_shortcuts(self, text):
        bind=[("<Control-b>",lambda: self.current_frame().controller.toggle_tag("bold")),("<Control-i>",lambda: self.current_frame().controller.toggle_tag("italic")),
            ("<Control-u>",lambda: self.current_frame().controller.toggle_tag("underline")),("<Control-Shift-S>",lambda: self.current_frame().controller.toggle_tag("strikethrough")),
            ("<Control-Alt-Key-1>",lambda: self.current_frame().controller.apply_header(1)),("<Control-Alt-Key-2>",lambda: self.current_frame().controller.apply_header(2)),
            ("<Control-Alt-Key-3>",lambda: self.current_frame().controller.apply_header(3)),("<Control-Alt-Key-4>",lambda: self.current_frame().controller.apply_header(4)),
            ("<Control-space>",lambda: self.current_frame().controller.clear_formatting())]
        for seq, fn in bind:
            text.bind(seq, lambda e,f=fn:(f(),"break")[1])

    def _toggle_toolbar(self):
        self.toolbar_host.pack_forget() if not self.toolbar_visible.get() else self.toolbar_host.pack(fill=tk.X, before=self.notebook)

    def _switch_mode(self, mode: str):
        self.current_tab().mode = mode
        self._update_status()

    def _open_file(self, ink: bool = False):
        path = filedialog.askopenfilename(filetypes=[("Inkline Rich Text", "*.ink"), ("All files", "*.*")]) if ink else filedialog.askopenfilename()
        if not path:
            return
        self._new_tab(); tab = self.current_tab(); text = self.current_text()
        tab.path = path; tab.title = Path(path).name
        if path.endswith(".ink"):
            payload = load_ink_document(path)
            text.delete("1.0", tk.END); text.insert("1.0", payload.get("content", ""))
            tab.mode = payload.get("mode", "Rich Text")
            for span in payload.get("tags", []):
                text.tag_add(span["tag"], span["start"], span["end"])
                if span["tag"].startswith("fg_") and "foreground" in span:
                    text.tag_configure(span["tag"], foreground=span["foreground"])
            text.mark_set(tk.INSERT, payload.get("cursor", "1.0"))
        else:
            text.delete("1.0", tk.END); text.insert("1.0", read_text(path, self.settings["encoding"]))
            tab.mode = "Plain Text"
        self.notebook.tab(self.notebook.select(), text=tab.title)
        self._add_recent(path)

    def _save_file(self, save_as: bool = False, force_ink: bool = False):
        tab, text = self.current_tab(), self.current_text()
        if not tab.path or save_as:
            tab.path = filedialog.asksaveasfilename(defaultextension=".ink" if force_ink else ".txt")
            if not tab.path:
                return
        if Path(tab.path).exists():
            backup_file(tab.path)
        if tab.path.endswith(".ink") or force_ink:
            tags=[]
            for tag in text.tag_names():
                if tag=="sel":
                    continue
                for rng in text.tag_ranges(tag)[::2]:
                    pass
                ranges=text.tag_ranges(tag)
                for i in range(0,len(ranges),2):
                    item={"tag":tag,"start":str(ranges[i]),"end":str(ranges[i+1])}
                    if tag.startswith("fg_"):
                        item["foreground"]=text.tag_cget(tag,"foreground")
                    tags.append(item)
            payload={"metadata":build_metadata(),"mode":tab.mode,"content":text.get("1.0","end-1c"),"tags":tags,"cursor":text.index(tk.INSERT)}
            save_ink_document(tab.path,payload)
        else:
            write_text(tab.path, text.get("1.0", tk.END), self.settings["encoding"], self.settings["line_endings"])
        tab.title = Path(tab.path).name; tab.dirty = False
        self.notebook.tab(self.notebook.select(), text=tab.title)
        self._add_recent(tab.path); self._update_status()

    def _export(self, fmt: str):
        path = filedialog.asksaveasfilename(defaultextension="." + fmt.lower())
        if path:
            export_file(path, self.current_text().get("1.0", tk.END), fmt)

    def _find(self):
        q = simpledialog.askstring("Find", "Query")
        if not q:
            return
        self.settings["search_history"] = ([q] + self.settings["search_history"])[:20]
        text = self.current_text().get("1.0", tk.END)
        matches = find_matches(text, q)
        self.status.config(text=f"Found {len(matches)} matches")

    def _replace(self):
        q = simpledialog.askstring("Replace", "Find")
        r = simpledialog.askstring("Replace", "Replace with")
        if q is None or r is None:
            return
        txt = self.current_text(); content = txt.get("1.0", tk.END).replace(q, r)
        txt.delete("1.0", tk.END); txt.insert("1.0", content)

    def _goto_line(self):
        line = simpledialog.askinteger("Go To", "Line")
        if line:
            self.current_text().mark_set(tk.INSERT, f"{line}.0")

    def _rewrite(self, fn):
        t = self.current_text(); data = t.get("1.0", tk.END)
        t.delete("1.0", tk.END); t.insert("1.0", fn(data))

    def _format_json(self):
        try:
            self._rewrite(format_json)
        except Exception as exc:
            messagebox.showerror("Invalid JSON", str(exc))

    def _zoom(self, delta: int):
        tab = self.current_tab(); tab.zoom = max(50, min(300, tab.zoom + delta))
        self.current_text().config(font=(self.settings["font_family"], int(self.settings["font_size"] * tab.zoom / 100)))
        self._update_status()

    def _toggle_wrap(self):
        self.settings["word_wrap"] = not self.settings["word_wrap"]
        self.current_text().config(wrap=tk.WORD if self.settings["word_wrap"] else tk.NONE)

    def _focus_mode(self):
        self.sidebar.pack_forget() if self.sidebar.winfo_ismapped() else self.main.add(self.sidebar)

    def _toggle_topmost(self):
        self.settings["always_on_top"] = not self.settings["always_on_top"]
        self.root.attributes("-topmost", self.settings["always_on_top"])

    def _rename_current(self):
        tab = self.current_tab()
        if not tab.path:
            return
        new_name = simpledialog.askstring("Rename", "New file name")
        if new_name:
            new_path = str(Path(tab.path).with_name(new_name))
            os.rename(tab.path, new_path)
            tab.path = new_path; tab.title = Path(new_path).name
            self.notebook.tab(self.notebook.select(), text=tab.title)

    def _duplicate_current(self):
        tab = self.current_tab()
        if not tab.path:
            return
        dup = str(Path(tab.path).with_stem(Path(tab.path).stem + "_copy"))
        write_text(dup, self.current_text().get("1.0", tk.END))
        self._add_recent(dup)

    def _on_change(self):
        tab = self.current_tab(); tab.dirty = True
        self._draw_line_numbers(); self._update_status()

    def _draw_line_numbers(self):
        frame = self.current_frame(); text, nums = frame.text, frame.nums
        lines = int(text.index("end-1c").split(".")[0])
        nums.config(state=tk.NORMAL); nums.delete("1.0", tk.END)
        nums.insert("1.0", "\n".join(map(str, range(1, lines + 1))))
        nums.config(state=tk.DISABLED)

    def _show_context_menu(self, event):
        text=self.current_text()
        if text.tag_ranges("sel"):
            self.current_frame().context_menu.tk_popup(event.x_root, event.y_root)

    def _paste_plain(self):
        try:
            data = self.root.clipboard_get()
            self.current_text().insert(tk.INSERT, data)
        except tk.TclError:
            pass

    def _update_status(self):
        text = self.current_text().get("1.0", "end-1c")
        idx = self.current_text().index(tk.INSERT)
        tab = self.current_tab()
        ln,col = idx.split(".")
        self.status.config(text=f"Ln {ln}, Col {int(col)+1} | Chars {len(text)} | Words {word_count(text)} | Read {reading_time_minutes(text)} min | {self.settings['encoding']} | {tab.zoom}% | {self.settings['line_endings']} | {tab.mode}")

    def _add_recent(self, path: str):
        if path in self.recent_files:
            self.recent_files.remove(path)
        self.recent_files.insert(0, path)
        self.recent_files = self.recent_files[:20]
        self.sidebar_list.delete(0, tk.END)
        for f in self.recent_files:
            self.sidebar_list.insert(tk.END, f)

    def _set_theme(self, name: str):
        self.theme_manager.set_theme(name)
        self.apply_theme()

    def apply_theme(self):
        t = self.theme_manager.current()
        self.root.configure(bg=t.bg); self.sidebar.configure(bg=t.sidebar_bg); self.center.configure(bg=t.bg)
        self.status.configure(bg=t.panel_bg, fg=t.fg)
        self.sidebar_list.configure(bg=t.panel_bg, fg=t.fg, selectbackground=t.accent)
        for tab_id in self.tabs:
            frame = self.root.nametowidget(tab_id)
            frame.text.configure(bg=t.bg, fg=t.fg, insertbackground=t.cursor, selectbackground=t.accent)
            frame.nums.configure(bg=t.sidebar_bg, fg=t.muted)

    def _schedule_autosave(self):
        self.root.after(self.settings["autosave_seconds"] * 1000, self._autosave)

    def _autosave(self):
        for tab in self.tabs.values():
            if tab.path and tab.dirty:
                frame = self.root.nametowidget(next(k for k, v in self.tabs.items() if v is tab))
                write_text(tab.path, frame.text.get("1.0", tk.END))
                tab.dirty = False
        self._save_workspace()
        self._schedule_autosave()

    def _save_workspace(self):
        data = {
            "geometry": self.root.geometry(), "theme": self.settings["theme"], "open_folders": self.open_folders,
            "tabs": [{"path": t.path, "title": t.title, "cursor": self.root.nametowidget(k).text.index(tk.INSERT), "zoom": t.zoom} for k, t in self.tabs.items()],
        }
        self.workspace.save(data)
        save_settings(self.settings)

    def _restore_workspace(self):
        data = self.workspace.load()
        if not data:
            return
        self.root.geometry(data.get("geometry", "1200x760"))
        self._set_theme(data.get("theme", "Dark"))

    def _close(self):
        if any(t.dirty for t in self.tabs.values()):
            if not messagebox.askyesno("Unsaved changes", "Exit with unsaved changes?"):
                return
        self._save_workspace()
        self.root.destroy()
