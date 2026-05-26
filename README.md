# Random Apps

This repository contains **two separate desktop apps**:

1. **Inkline** — a modern lightweight text editor.
2. **Steam Key Manager** — a GUI utility for organizing and tracking Steam keys.

> These apps are independent. They are not combined into one program.

---

## App 1: Inkline

Simple notes, sharper tools.

## Run locally

```bash
python -m inkline.main
```

## Compile a desktop executable

Install build dependency:

```bash
python -m pip install pyinstaller
```

Build app bundle:

```bash
python tools/build_app.py
```

Build single-file executable:

```bash
python tools/build_app.py --onefile
```

Output is written to `dist/`.
**Simple notes, sharper tools.**

Inkline is a modern lightweight desktop text editor built in **Python 3.14 using Tkinter**. Inspired by Windows Notepad, Inkline expands the classic experience with modern themes, workspaces, organisation tools, advanced editing systems, and developer-focused utilities while remaining fast, clean, and lightweight.

Inkline is designed for:

* Writing
* Coding
* Quick notes
* Documentation
* Markdown editing
* Workspace organisation
* Lightweight productivity

Unlike bloated editors or browser-based note apps, Inkline focuses on native desktop performance, fast launch times, and simplicity.

---

# Features

## File Management

* New files
* Open existing files
* Save / Save As
* Auto-save system
* Recent files tracking
* Multiple tabs
* Backup recovery
* Duplicate file support
* Rename current file
* Export support:

  * TXT
  * Markdown
  * HTML
  * JSON
  * PDF

---

## Editing Tools

* Undo / Redo
* Cut / Copy / Paste
* Find & Replace
* Replace All
* Regex search
* Go To Line
* Word wrap
* Zoom controls
* Font customisation
* Auto-indent
* Matching brackets
* Encoding switcher
* CRLF/LF switching

---

## Writing Features

* Focus Mode
* Typewriter Mode
* Reading time estimates
* Word count
* Character count
* Paragraph count
* Smart quotes
* Auto-capitalisation
* Empty line trimming
* Double-space cleanup

---

## Developer Features

* Syntax highlighting architecture
* JSON formatter
* Markdown preview
* HTML preview
* Advanced search systems
* Line numbering
* Search history
* Workspace restoration

---

## Workspace System

Inkline includes a full Workspace Mode system.

Workspaces automatically restore:

* Open tabs
* Cursor positions
* Window size
* Sidebar state
* Theme
* Zoom level
* Open folders

When reopening Inkline, everything restores exactly where it was left.

---

# Themes

Inkline includes multiple built-in themes:

| Theme                | Description                         |
| -------------------- | ----------------------------------- |
| Light Theme          | Classic Windows-inspired appearance |
| Dark Theme           | Modern dark grey UI                 |
| AMOLED Theme         | Pure black OLED-friendly theme      |
| Neon Purple Theme    | Cyber-style purple/pink theme       |
| Ocean Blue Theme     | Calm blue interface                 |
| Retro Terminal Theme | Green-on-black terminal style       |

Theme settings are saved automatically.

Custom accent colours are also supported.

---

# UI Design

Inkline uses a modern desktop layout featuring:

* Custom title bar
* Menu bar
* Sidebar
* Multi-tab system
* Main editor area
* Bottom status bar

The status bar displays:

* Line number
* Column number
* Character count
* Word count
* Encoding type
* Zoom level
* Line ending type

---

# Technical Information

| Component    | Technology  |
| ------------ | ----------- |
| Language     | Python 3.14 |
| UI Framework | Tkinter     |
| Architecture | Modular OOP |
| Platform     | Windows     |
| License      | GPL v3      |

---

# Project Structure

```text id="jg0ow6"
Inkline/
│
├── main.py
├── requirements.txt
├── LICENSE
├── README.md
│
├── assets/
├── config/
├── themes/
├── ui/
├── editor/
├── workspace/
├── utils/
└── backups/
```

---

# Performance Goals

Inkline is designed to:

* Launch quickly
* Stay lightweight
* Use minimal RAM
* Handle large text files smoothly
* Avoid unnecessary background processes
* Feel responsive during editing

---

# Planned Features

Future updates may include:

* Plugin system
* Split-view editing
* Live collaboration
* AI writing tools
* Portable mode
* Built-in terminal
* Session snapshots
* Cloud sync
* Advanced syntax highlighting
* Git integration

---

# Installation

## Requirements

* Python 3.14
* Windows 10/11

---

## Clone Repository

```bash
git clone https://github.com/USERNAME/Inkline.git
cd Inkline
```

---

## Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Run Inkline

```bash
python main.py
```

---

# License

Inkline is licensed under the **GNU General Public License v3.0 (GPL v3)**.

You may:

* Use the software
* Modify the software
* Share modified versions

You may not:

* Remove original credits
* Redistribute closed-source versions
* Rebrand the project as your own

Commercial redistribution or resale without permission from the original creator is not supported.

See the `LICENSE` file for full details.

---

# Design Philosophy

Inkline exists to prove that a text editor can:

* Stay lightweight
* Look modern
* Launch instantly
* Remain simple
* Still provide powerful tools

No bloated ribbons.
No forced cloud systems.
No unnecessary complexity.

Just a fast modern desktop editor built properly.

---

# Status

Inkline is currently in active development.


---

## App 2: Steam Key Manager

Steam Key Manager is a separate Tkinter desktop app for importing, sorting, and tracking Steam keys.

### Run locally

```bash
python steam_key_manager.py
```

### What it does

* Load key lists from file
* Track available vs used keys
* Move keys between states
* Save/export updated key lists
* Switch between built-in themes
