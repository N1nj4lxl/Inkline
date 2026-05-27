import asyncio
import json
import threading
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import discord
from discord.ext import commands


@dataclass
class GuildRoleSnapshot:
    guild_id: int
    guild_name: str
    roles: list[tuple[int, str]]


class KeyDistributor:
    def __init__(self):
        self.keys: list[str] = []
        self.claimed: dict[int, list[str]] = defaultdict(list)
        self.allowed_users: set[int] = set()
        self.allowed_roles_by_guild: dict[int, set[int]] = defaultdict(set)
        self.default_count = 1
        self.custom_commands: dict[str, str] = {}
        self.lock = threading.Lock()

    def load_keys_from_file(self, file_path: str):
        path = Path(file_path)
        lines = path.read_text(encoding="utf-8").splitlines()
        clean = [line.strip() for line in lines if line.strip()]
        deduped = list(dict.fromkeys(clean))
        with self.lock:
            self.keys = deduped

    def save_state(self, file_path: str):
        with self.lock:
            data = {
                "remaining_keys": self.keys,
                "allowed_users": sorted(self.allowed_users),
                "default_count": self.default_count,
                "custom_commands": self.custom_commands,
                "claimed": {str(uid): vals for uid, vals in self.claimed.items()},
                "allowed_roles_by_guild": {
                    str(gid): sorted(role_ids) for gid, role_ids in self.allowed_roles_by_guild.items()
                },
            }
        Path(file_path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_state(self, file_path: str):
        data = json.loads(Path(file_path).read_text(encoding="utf-8"))
        with self.lock:
            self.keys = list(data.get("remaining_keys", []))
            self.allowed_users = {int(u) for u in data.get("allowed_users", [])}
            self.default_count = int(data.get("default_count", 1))
            loaded_commands = data.get("custom_commands", {})
            self.custom_commands = {
                self._normalize_command_name(name): str(response)
                for name, response in loaded_commands.items()
                if self._normalize_command_name(name) and str(response).strip()
            }
            restored = defaultdict(list)
            for uid, vals in data.get("claimed", {}).items():
                restored[int(uid)] = list(vals)
            self.claimed = restored
            role_map = defaultdict(set)
            for gid, role_ids in data.get("allowed_roles_by_guild", {}).items():
                role_map[int(gid)] = {int(role_id) for role_id in role_ids}
            self.allowed_roles_by_guild = role_map

    @staticmethod
    def _normalize_command_name(name: str) -> str:
        clean = "".join(ch for ch in name.strip().lower() if ch.isalnum() or ch == "_")
        return clean

    def upsert_custom_command(self, name: str, response: str) -> str:
        normalized = self._normalize_command_name(name)
        if not normalized:
            raise ValueError("Command name must contain letters, numbers, or underscores.")
        reply = response.strip()
        if not reply:
            raise ValueError("Command response cannot be empty.")
        with self.lock:
            self.custom_commands[normalized] = reply
        return normalized

    def remove_custom_command(self, name: str) -> bool:
        normalized = self._normalize_command_name(name)
        with self.lock:
            return self.custom_commands.pop(normalized, None) is not None

    def add_allowed_user(self, user_id: int):
        with self.lock:
            self.allowed_users.add(user_id)

    def remove_allowed_user(self, user_id: int):
        with self.lock:
            self.allowed_users.discard(user_id)

    def grant_role(self, guild_id: int, role_id: int):
        with self.lock:
            self.allowed_roles_by_guild[guild_id].add(role_id)

    def revoke_role(self, guild_id: int, role_id: int):
        with self.lock:
            roles = self.allowed_roles_by_guild.get(guild_id)
            if not roles:
                return
            roles.discard(role_id)

    def user_has_role_access(self, guild_id: int, role_ids: list[int]) -> bool:
        with self.lock:
            allowed_roles = self.allowed_roles_by_guild.get(guild_id, set())
            return any(role_id in allowed_roles for role_id in role_ids)

    def give_keys(self, user_id: int, count: int | None = None) -> list[str]:
        with self.lock:
            n = count if count is not None else self.default_count
            n = max(1, n)
            if not self.keys:
                return []
            given = self.keys[:n]
            self.keys = self.keys[n:]
            self.claimed[user_id].extend(given)
            return given

    def summary(self):
        with self.lock:
            return {
                "remaining": len(self.keys),
                "allowed_count": len(self.allowed_users),
                "claimed_total": sum(len(v) for v in self.claimed.values()),
            }


class BotController:
    def __init__(self, distributor: KeyDistributor, log_cb, guild_sync_cb):
        self.distributor = distributor
        self.log_cb = log_cb
        self.guild_sync_cb = guild_sync_cb
        self.loop = None
        self.thread = None
        self.bot = None
        self.custom_command_names: set[str] = set()
        self.running = False

    def _build_bot(self, prefix: str):
        intents = discord.Intents.default()
        intents.message_content = True
        bot = commands.Bot(command_prefix=prefix, intents=intents)

        @bot.event
        async def on_ready():
            self.log_cb(f"Logged in as {bot.user} (ID: {bot.user.id})")
            snapshots = []
            for guild in bot.guilds:
                me = guild.me
                if me is None:
                    continue
                manageable_roles = [
                    (role.id, role.name)
                    for role in guild.roles
                    if role.position < me.top_role.position and not role.managed
                ]
                manageable_roles.sort(key=lambda item: item[1].lower())
                snapshots.append(
                    GuildRoleSnapshot(
                        guild_id=guild.id,
                        guild_name=f"{guild.name} ({guild.id})",
                        roles=manageable_roles,
                    )
                )
            self.guild_sync_cb(snapshots)

        @bot.command(name="getkeys")
        async def get_keys(ctx, count: int | None = None):
            user_id = ctx.author.id
            if isinstance(ctx.channel, discord.DMChannel) or ctx.guild is None:
                await ctx.reply("Use this command inside a server channel.")
                return

            has_role_access = self.distributor.user_has_role_access(
                ctx.guild.id, [role.id for role in ctx.author.roles]
            )
            if not has_role_access and user_id not in self.distributor.allowed_users:
                await ctx.reply("You are not allowed to receive keys.")
                return
            keys = self.distributor.give_keys(user_id, count)
            if not keys:
                await ctx.reply("No keys are available right now.")
                return

            joined = "\n".join(keys)
            try:
                await ctx.author.send(f"Your keys:\n{joined}")
                await ctx.reply(f"Sent {len(keys)} key(s) to your DM.")
            except discord.Forbidden:
                await ctx.reply("I can't DM you. Please open your DMs and try again.")

            self.log_cb(f"Gained keys -> {ctx.author} ({ctx.author.id}): {', '.join(keys)}")

        self._register_custom_commands(bot)
        return bot

    def _register_custom_commands(self, bot):
        for command_name in list(self.custom_command_names):
            cmd = bot.get_command(command_name)
            if cmd:
                bot.remove_command(command_name)
        self.custom_command_names.clear()

        for command_name, response in self.distributor.custom_commands.items():
            async def custom_reply(ctx, text=response):
                await ctx.reply(text)

            bot.command(name=command_name)(custom_reply)
            self.custom_command_names.add(command_name)

    def sync_custom_commands(self):
        if not self.running or not self.bot or not self.loop:
            return

        def apply_changes():
            self._register_custom_commands(self.bot)

        self.loop.call_soon_threadsafe(apply_changes)

    def start(self, token: str, prefix: str):
        if self.running:
            self.log_cb("Bot is already running.")
            return

        def runner():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.bot = self._build_bot(prefix)
            self.running = True
            try:
                self.loop.run_until_complete(self.bot.start(token))
            except Exception as exc:
                self.log_cb(f"Bot crashed: {exc}")
            finally:
                self.running = False

        self.thread = threading.Thread(target=runner, daemon=True)
        self.thread.start()
        self.log_cb("Bot thread started.")

    def stop(self):
        if not self.running or not self.bot or not self.loop:
            self.log_cb("Bot is not running.")
            return

        async def shutdown():
            await self.bot.close()

        fut = asyncio.run_coroutine_threadsafe(shutdown(), self.loop)
        try:
            fut.result(timeout=10)
            self.log_cb("Bot stopped.")
        except Exception as exc:
            self.log_cb(f"Failed to stop bot cleanly: {exc}")


class Dashboard:
    THEMES = {
        "True Dark": {
            "bg": "#0e0e10",
            "panel": "#17171c",
            "input": "#1f2027",
            "text": "#f5f7ff",
            "muted": "#adb5d8",
            "accent": "#6c7bff",
            "accent_active": "#8d98ff",
            "border": "#2b2e3a",
        },
        "Dark Pink": {
            "bg": "#140f16",
            "panel": "#211725",
            "input": "#2a1e30",
            "text": "#ffeaf6",
            "muted": "#ddb3cf",
            "accent": "#ff4fa3",
            "accent_active": "#ff79bc",
            "border": "#3f2a47",
        },
    }

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Discord Key Distributor Dashboard")
        self.root.geometry("950x640")
        self.style = ttk.Style(self.root)

        self.dist = KeyDistributor()
        self.controller = BotController(self.dist, self.log, self.sync_guild_tabs)

        self.token_var = tk.StringVar()
        self.prefix_var = tk.StringVar(value="!")
        self.default_count_var = tk.StringVar(value="1")
        self.user_id_var = tk.StringVar()
        self.command_name_var = tk.StringVar()
        self.command_response_var = tk.StringVar()
        self.theme_var = tk.StringVar(value="True Dark")
        self.guild_tabs: dict[int, dict] = {}

        self._build_ui()
        self.apply_theme(self.theme_var.get())
        self.refresh_lists()

    def _build_ui(self):
        wrapper = ttk.Frame(self.root, padding=10)
        wrapper.pack(fill="both", expand=True)

        top = ttk.LabelFrame(wrapper, text="Bot Controls", padding=8)
        top.pack(fill="x", pady=(0, 10))

        ttk.Label(top, text="Token:").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.token_var, show="*", width=60).grid(row=0, column=1, padx=6, sticky="we")

        ttk.Label(top, text="Prefix:").grid(row=0, column=2, padx=(10, 0), sticky="w")
        ttk.Entry(top, textvariable=self.prefix_var, width=8).grid(row=0, column=3, padx=6, sticky="w")

        ttk.Button(top, text="Start Bot", command=self.start_bot).grid(row=0, column=4, padx=4)
        ttk.Button(top, text="Stop Bot", command=self.stop_bot).grid(row=0, column=5, padx=4)
        ttk.Label(top, text="Theme:").grid(row=1, column=0, pady=(8, 0), sticky="w")
        theme_combo = ttk.Combobox(
            top,
            textvariable=self.theme_var,
            values=list(self.THEMES.keys()),
            state="readonly",
            width=14,
        )
        theme_combo.grid(row=1, column=1, sticky="w", padx=6, pady=(8, 0))
        theme_combo.bind("<<ComboboxSelected>>", lambda _e: self.apply_theme(self.theme_var.get()))
        top.columnconfigure(1, weight=1)

        mid = ttk.Frame(wrapper)
        mid.pack(fill="both", expand=True)

        left = ttk.LabelFrame(mid, text="Keys", padding=8)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))

        ttk.Button(left, text="Load Keys File", command=self.load_keys).pack(anchor="w", pady=(0, 8))
        ttk.Label(left, text="Default keys per request:").pack(anchor="w")
        ttk.Entry(left, textvariable=self.default_count_var, width=10).pack(anchor="w", pady=(0, 8))
        ttk.Button(left, text="Apply Default", command=self.apply_default_count).pack(anchor="w", pady=(0, 8))

        self.keys_list = tk.Listbox(left)
        self.keys_list.pack(fill="both", expand=True)

        right = ttk.LabelFrame(mid, text="Allowed Users", padding=8)
        right.pack(side="left", fill="both", expand=True)

        row = ttk.Frame(right)
        row.pack(fill="x", pady=(0, 8))
        ttk.Entry(row, textvariable=self.user_id_var).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(row, text="Add", command=self.add_user).pack(side="left", padx=3)
        ttk.Button(row, text="Remove", command=self.remove_user).pack(side="left", padx=3)

        self.users_list = tk.Listbox(right)
        self.users_list.pack(fill="both", expand=True)

        commands_frame = ttk.LabelFrame(mid, text="Custom Commands", padding=8)
        commands_frame.pack(side="left", fill="both", expand=True, padx=(8, 0))

        ttk.Label(commands_frame, text="Command name (without prefix):").pack(anchor="w")
        ttk.Entry(commands_frame, textvariable=self.command_name_var).pack(fill="x", pady=(0, 6))
        ttk.Label(commands_frame, text="Reply message:").pack(anchor="w")
        ttk.Entry(commands_frame, textvariable=self.command_response_var).pack(fill="x", pady=(0, 8))

        command_buttons = ttk.Frame(commands_frame)
        command_buttons.pack(fill="x", pady=(0, 8))
        ttk.Button(command_buttons, text="Create / Update", command=self.add_or_update_command).pack(side="left", padx=(0, 6))
        ttk.Button(command_buttons, text="Remove", command=self.remove_command).pack(side="left")

        self.commands_list = tk.Listbox(commands_frame)
        self.commands_list.pack(fill="both", expand=True)

        gained_frame = ttk.LabelFrame(mid, text="Users Who Gained Keys", padding=8)
        gained_frame.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.gained_list = tk.Listbox(gained_frame)
        self.gained_list.pack(fill="both", expand=True)

        role_frame = ttk.LabelFrame(wrapper, text="Server Role Access", padding=8)
        role_frame.pack(fill="both", expand=True, pady=(10, 0))
        self.guild_notebook = ttk.Notebook(role_frame)
        self.guild_notebook.pack(fill="both", expand=True)

        bottom = ttk.LabelFrame(wrapper, text="State & Logs", padding=8)
        bottom.pack(fill="both", expand=True, pady=(10, 0))

        controls = ttk.Frame(bottom)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Button(controls, text="Save State", command=self.save_state).pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="Load State", command=self.load_state).pack(side="left", padx=(0, 6))
        self.stats_label = ttk.Label(controls, text="Remaining: 0 | Allowed: 0 | Claimed: 0")
        self.stats_label.pack(side="right")

        self.log_text = tk.Text(bottom, height=10, state="disabled")
        self.log_text.pack(fill="both", expand=True)

    def apply_theme(self, theme_name: str):
        c = self.THEMES[theme_name]
        self.style.theme_use("clam")
        self.root.configure(bg=c["bg"])

        self.style.configure("TFrame", background=c["bg"])
        self.style.configure("TLabelframe", background=c["panel"], bordercolor=c["border"], relief="solid")
        self.style.configure("TLabelframe.Label", background=c["panel"], foreground=c["text"])
        self.style.configure("TLabel", background=c["panel"], foreground=c["text"])
        self.style.configure("TEntry", fieldbackground=c["input"], foreground=c["text"], bordercolor=c["border"])
        self.style.map("TEntry", fieldbackground=[("readonly", c["input"])])
        self.style.configure(
            "TButton",
            background=c["accent"],
            foreground="white",
            borderwidth=0,
            focusthickness=0,
            padding=6,
        )
        self.style.map("TButton", background=[("active", c["accent_active"])])
        self.style.configure(
            "TCombobox",
            fieldbackground=c["input"],
            background=c["input"],
            foreground=c["text"],
            arrowcolor=c["text"],
        )
        self.style.map("TCombobox", fieldbackground=[("readonly", c["input"])])

        for listbox in [self.keys_list, self.users_list, self.commands_list, self.gained_list]:
            listbox.configure(
                bg=c["input"],
                fg=c["text"],
                selectbackground=c["accent"],
                selectforeground="white",
                highlightthickness=1,
                highlightbackground=c["border"],
                relief="flat",
            )

        self.log_text.configure(
            bg=c["input"],
            fg=c["text"],
            insertbackground=c["text"],
            highlightthickness=1,
            highlightbackground=c["border"],
            relief="flat",
        )

    def log(self, text: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self.refresh_lists()

    def refresh_lists(self):
        self.keys_list.delete(0, "end")
        for k in self.dist.keys:
            self.keys_list.insert("end", k)

        self.users_list.delete(0, "end")
        for uid in sorted(self.dist.allowed_users):
            self.users_list.insert("end", str(uid))

        self.commands_list.delete(0, "end")
        for name, response in sorted(self.dist.custom_commands.items()):
            self.commands_list.insert("end", f"{name} -> {response}")

        self.gained_list.delete(0, "end")
        for uid, keys in sorted(self.dist.claimed.items()):
            if keys:
                self.gained_list.insert("end", f"{uid} ({len(keys)} key(s))")

        s = self.dist.summary()
        self.stats_label.config(
            text=f"Remaining: {s['remaining']} | Allowed: {s['allowed_count']} | Claimed: {s['claimed_total']}"
        )
        self.refresh_guild_role_lists()

    def sync_guild_tabs(self, snapshots: list[GuildRoleSnapshot]):
        def apply():
            for tab_info in self.guild_tabs.values():
                self.guild_notebook.forget(tab_info["frame"])
            self.guild_tabs.clear()

            for snapshot in sorted(snapshots, key=lambda s: s.guild_name.lower()):
                frame = ttk.Frame(self.guild_notebook, padding=8)
                self.guild_notebook.add(frame, text=snapshot.guild_name[:36])

                listbox = tk.Listbox(frame)
                listbox.pack(fill="both", expand=True, pady=(0, 8))

                btn_row = ttk.Frame(frame)
                btn_row.pack(fill="x")
                ttk.Button(
                    btn_row,
                    text="Grant Selected Role",
                    command=lambda gid=snapshot.guild_id, lb=listbox: self.grant_selected_role(gid, lb),
                ).pack(side="left", padx=(0, 6))
                ttk.Button(
                    btn_row,
                    text="Revoke Selected Role",
                    command=lambda gid=snapshot.guild_id, lb=listbox: self.revoke_selected_role(gid, lb),
                ).pack(side="left")

                self.guild_tabs[snapshot.guild_id] = {
                    "frame": frame,
                    "listbox": listbox,
                    "roles": snapshot.roles,
                }
            self.refresh_guild_role_lists()
            self.apply_theme(self.theme_var.get())

        self.root.after(0, apply)

    def refresh_guild_role_lists(self):
        for guild_id, info in self.guild_tabs.items():
            listbox = info["listbox"]
            listbox.delete(0, "end")
            allowed = self.dist.allowed_roles_by_guild.get(guild_id, set())
            for role_id, role_name in info["roles"]:
                marker = "✅" if role_id in allowed else "❌"
                listbox.insert("end", f"{marker} {role_name} ({role_id})")

    def grant_selected_role(self, guild_id: int, listbox: tk.Listbox):
        idx = listbox.curselection()
        if not idx:
            return
        role_id, role_name = self.guild_tabs[guild_id]["roles"][idx[0]]
        self.dist.grant_role(guild_id, role_id)
        self.log(f"Granted key access for role '{role_name}' in guild {guild_id}")

    def revoke_selected_role(self, guild_id: int, listbox: tk.Listbox):
        idx = listbox.curselection()
        if not idx:
            return
        role_id, role_name = self.guild_tabs[guild_id]["roles"][idx[0]]
        self.dist.revoke_role(guild_id, role_id)
        self.log(f"Revoked key access for role '{role_name}' in guild {guild_id}")

    def load_keys(self):
        path = filedialog.askopenfilename(filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.dist.load_keys_from_file(path)
            self.log(f"Loaded keys from {path}")
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def apply_default_count(self):
        try:
            value = max(1, int(self.default_count_var.get()))
            self.dist.default_count = value
            self.log(f"Default key count set to {value}")
        except ValueError:
            messagebox.showwarning("Input Error", "Default count must be an integer.")

    def add_user(self):
        try:
            uid = int(self.user_id_var.get().strip())
            self.dist.add_allowed_user(uid)
            self.log(f"Added allowed user {uid}")
        except ValueError:
            messagebox.showwarning("Input Error", "User ID must be a number.")

    def remove_user(self):
        try:
            uid = int(self.user_id_var.get().strip())
            self.dist.remove_allowed_user(uid)
            self.log(f"Removed allowed user {uid}")
        except ValueError:
            messagebox.showwarning("Input Error", "User ID must be a number.")

    def save_state(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            self.dist.save_state(path)
            self.log(f"Saved state to {path}")
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def add_or_update_command(self):
        try:
            command_name = self.dist.upsert_custom_command(
                self.command_name_var.get(),
                self.command_response_var.get(),
            )
            self.controller.sync_custom_commands()
            self.log(f"Saved custom command '{command_name}'")
        except ValueError as exc:
            messagebox.showwarning("Input Error", str(exc))

    def remove_command(self):
        removed = self.dist.remove_custom_command(self.command_name_var.get())
        if removed:
            self.controller.sync_custom_commands()
            self.log(f"Removed custom command '{self.command_name_var.get().strip()}'")
            return
        messagebox.showwarning("Not Found", "That command does not exist.")

    def load_state(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.dist.load_state(path)
            self.default_count_var.set(str(self.dist.default_count))
            self.log(f"Loaded state from {path}")
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def start_bot(self):
        token = self.token_var.get().strip()
        prefix = self.prefix_var.get().strip() or "!"
        if not token:
            messagebox.showwarning("Missing Token", "Please enter your bot token.")
            return
        self.controller.start(token, prefix)

    def stop_bot(self):
        self.controller.stop()


def main():
    root = tk.Tk()
    Dashboard(root)
    root.mainloop()


if __name__ == "__main__":
    main()
