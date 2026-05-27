import asyncio
import csv
import json
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import discord
from discord.ext import commands

APP_DIR = Path(__file__).resolve().parent / "dashboard_config"
APP_DIR.mkdir(exist_ok=True)
AUTOSAVE_PATH = APP_DIR / "state.json"
LOG_PATH = APP_DIR / "dashboard.log"


@dataclass
class GuildRoleSnapshot:
    guild_id: int
    guild_name: str
    roles: list[tuple[int, str]]


@dataclass
class ClaimEvent:
    user_id: int
    username: str
    key: str
    timestamp: str


@dataclass
class ServerSettings:
    prefix: str = "!"
    allowed_roles: set[int] = field(default_factory=set)
    default_keys_per_request: int = 1
    claim_cooldown_hours: int = 24


class KeyDistributor:
    def __init__(self):
        self.keys: list[str] = []
        self.claimed: dict[int, list[str]] = defaultdict(list)
        self.claim_history: list[ClaimEvent] = []
        self.allowed_users: set[int] = set()
        self.default_count = 1
        self.custom_commands: dict[str, str] = {}
        self.server_settings: dict[int, ServerSettings] = defaultdict(ServerSettings)
        self.username_cache: dict[int, str] = {}
        self.last_claim_at: dict[int, str] = {}
        self.max_claims_per_user = 1
        self.prevent_duplicate_claim = True
        self.lock_mode = False
        self.lock = threading.Lock()

    def import_preview(self, file_path: str):
        lines = Path(file_path).read_text(encoding="utf-8").splitlines()
        stripped = [line.strip() for line in lines]
        non_empty = [line for line in stripped if line]
        deduped = list(dict.fromkeys(non_empty))
        return {
            "total_lines": len(lines),
            "empty_removed": len(lines) - len(non_empty),
            "duplicates_removed": len(non_empty) - len(deduped),
            "final_count": len(deduped),
            "keys": deduped,
        }

    def load_keys(self, keys: list[str]):
        with self.lock:
            self.keys = list(keys)

    def load_allowed_users_from_lines(self, lines: list[str]) -> tuple[int, int]:
        added = 0
        skipped = 0
        with self.lock:
            for line in lines:
                clean = line.strip().split(",")[0]
                if not clean:
                    continue
                try:
                    uid = int(clean)
                except ValueError:
                    skipped += 1
                    continue
                if uid in self.allowed_users:
                    skipped += 1
                else:
                    self.allowed_users.add(uid)
                    added += 1
        return added, skipped

    def can_claim(self, user_id: int, guild_id: int, role_ids: list[int]) -> tuple[bool, str]:
        with self.lock:
            if self.lock_mode:
                return False, "Emergency lock mode is enabled."
            settings = self.server_settings[guild_id]
            has_role = any(rid in settings.allowed_roles for rid in role_ids)
            if user_id not in self.allowed_users and not has_role:
                return False, "User is not allowed by ID or role."
            if self.prevent_duplicate_claim and self.claimed.get(user_id):
                return False, "User already claimed and duplicate protection is enabled."
            if len(self.claimed.get(user_id, [])) >= self.max_claims_per_user:
                return False, f"User has reached max claims ({self.max_claims_per_user})."
            if user_id in self.last_claim_at:
                last = datetime.fromisoformat(self.last_claim_at[user_id])
                cooldown_end = last + timedelta(hours=settings.claim_cooldown_hours)
                if datetime.utcnow() < cooldown_end:
                    return False, f"Claim cooldown active until {cooldown_end.isoformat(timespec='seconds')} UTC"
        return True, "User can claim."

    def give_keys(self, user_id: int, username: str, guild_id: int, count: int | None = None) -> tuple[list[str], str]:
        with self.lock:
            settings = self.server_settings[guild_id]
            n = count if count is not None else settings.default_keys_per_request
            n = max(1, n)
            if not self.keys:
                return [], "No keys available."
            given = self.keys[:n]
            self.keys = self.keys[n:]
            self.claimed[user_id].extend(given)
            self.username_cache[user_id] = username
            now = datetime.utcnow().isoformat(timespec="seconds")
            self.last_claim_at[user_id] = now
            for key in given:
                self.claim_history.append(ClaimEvent(user_id, username, key, now))
            return given, "Keys granted."

    def save_state(self, file_path: str):
        with self.lock:
            data = {
                "remaining_keys": self.keys,
                "allowed_users": sorted(self.allowed_users),
                "default_count": self.default_count,
                "custom_commands": self.custom_commands,
                "claimed": {str(uid): vals for uid, vals in self.claimed.items()},
                "username_cache": {str(k): v for k, v in self.username_cache.items()},
                "claim_history": [e.__dict__ for e in self.claim_history],
                "server_settings": {
                    str(gid): {
                        "prefix": s.prefix,
                        "allowed_roles": sorted(s.allowed_roles),
                        "default_keys_per_request": s.default_keys_per_request,
                        "claim_cooldown_hours": s.claim_cooldown_hours,
                    }
                    for gid, s in self.server_settings.items()
                },
                "last_claim_at": self.last_claim_at,
                "max_claims_per_user": self.max_claims_per_user,
                "prevent_duplicate_claim": self.prevent_duplicate_claim,
                "lock_mode": self.lock_mode,
            }
        path = Path(file_path)
        if path.exists():
            stamp = datetime.utcnow().strftime("%Y-%m-%d_%H-%M")
            backup = path.with_name(f"state_backup_{stamp}.json")
            backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_state(self, file_path: str):
        data = json.loads(Path(file_path).read_text(encoding="utf-8"))
        with self.lock:
            self.keys = list(data.get("remaining_keys", []))
            self.allowed_users = {int(u) for u in data.get("allowed_users", [])}
            self.default_count = int(data.get("default_count", 1))
            self.custom_commands = data.get("custom_commands", {})
            self.claimed = defaultdict(list, {int(uid): vals for uid, vals in data.get("claimed", {}).items()})
            self.username_cache = {int(k): v for k, v in data.get("username_cache", {}).items()}
            self.claim_history = [ClaimEvent(**event) for event in data.get("claim_history", [])]
            loaded_server_settings = defaultdict(ServerSettings)
            for gid, values in data.get("server_settings", {}).items():
                loaded_server_settings[int(gid)] = ServerSettings(
                    prefix=values.get("prefix", "!"),
                    allowed_roles={int(v) for v in values.get("allowed_roles", [])},
                    default_keys_per_request=int(values.get("default_keys_per_request", 1)),
                    claim_cooldown_hours=int(values.get("claim_cooldown_hours", 24)),
                )
            self.server_settings = loaded_server_settings
            self.last_claim_at = {int(k): v for k, v in data.get("last_claim_at", {}).items()}
            self.max_claims_per_user = int(data.get("max_claims_per_user", 1))
            self.prevent_duplicate_claim = bool(data.get("prevent_duplicate_claim", True))
            self.lock_mode = bool(data.get("lock_mode", False))


class BotController:
    def __init__(self, distributor: KeyDistributor, log_cb, status_cb, guild_sync_cb):
        self.dist = distributor
        self.log_cb = log_cb
        self.status_cb = status_cb
        self.guild_sync_cb = guild_sync_cb
        self.loop = None
        self.bot = None
        self.running = False

    async def validate_token(self, token: str):
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        try:
            await bot.login(token)
            await bot.close()
            return True, "Token validation successful."
        except discord.LoginFailure:
            return False, "Invalid bot token"
        except Exception as exc:
            return False, f"Token validation failed: {exc}"

    def start(self, token: str, prefix: str):
        if self.running:
            self.log_cb("[Warning] Bot already running")
            return

        ok, msg = asyncio.run(self.validate_token(token))
        if not ok:
            self.status_cb("Offline")
            self.log_cb(f"[Error] {msg}")
            return

        def runner():
            intents = discord.Intents.default()
            intents.message_content = True
            self.bot = commands.Bot(command_prefix=prefix, intents=intents)
            self.status_cb("Starting")

            @self.bot.event
            async def on_ready():
                self.status_cb("Online")
                self.log_cb(f"[Success] Logged in as {self.bot.user}")
                snapshots = []
                for guild in self.bot.guilds:
                    snapshots.append(
                        GuildRoleSnapshot(
                            guild_id=guild.id,
                            guild_name=f"{guild.name} ({guild.id})",
                            roles=[(r.id, r.name) for r in guild.roles if not r.managed],
                        )
                    )
                self.guild_sync_cb(snapshots)

            @self.bot.command(name="getkeys")
            async def getkeys(ctx, count: int | None = None):
                if not ctx.guild:
                    await ctx.reply("Use this command inside a server channel.")
                    return
                can, reason = self.dist.can_claim(ctx.author.id, ctx.guild.id, [r.id for r in ctx.author.roles])
                if not can:
                    await ctx.reply(reason)
                    return
                keys, _ = self.dist.give_keys(ctx.author.id, str(ctx.author), ctx.guild.id, count)
                if not keys:
                    await ctx.reply("No keys available.")
                    return
                try:
                    await ctx.author.send("Your keys:\n" + "\n".join(keys))
                    await ctx.reply(f"Sent {len(keys)} key(s) in DM.")
                    self.log_cb(f"[Success] Gained keys -> {ctx.author} ({ctx.author.id})")
                except discord.Forbidden:
                    await ctx.reply("DM failed. Please enable DMs.")
                    self.log_cb("[Warning] DM failed for user")

            try:
                self.running = True
                self.bot.run(token)
            except Exception as exc:
                self.status_cb("Crashed")
                self.log_cb(f"[Error] Bot crashed: {exc}")
            finally:
                self.running = False
                if self.status_cb:
                    self.status_cb("Offline")

        threading.Thread(target=runner, daemon=True).start()


class Dashboard:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Discord Key Distributor - Modern Dashboard")
        self.root.geometry("1300x800")
        self.dist = KeyDistributor()
        self.status_var = tk.StringVar(value="Offline")
        self.token_var = tk.StringVar()
        self.show_token_var = tk.BooleanVar(value=False)
        self.search_vars = {name: tk.StringVar() for name in ["keys", "users", "claimed", "roles", "commands"]}
        self.controller = BotController(self.dist, self.log, self.set_status, self.sync_guilds)
        self.guild_data = {}
        self._build_ui()
        if AUTOSAVE_PATH.exists():
            self.dist.load_state(str(AUTOSAVE_PATH))
        self.refresh_all()

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)
        sidebar = ttk.Frame(main, width=180)
        sidebar.pack(side="left", fill="y")
        body = ttk.Frame(main)
        body.pack(side="left", fill="both", expand=True, padx=(10, 0))

        self.pages = {}
        self.page_stack = ttk.Frame(body)
        self.page_stack.pack(fill="both", expand=True)

        for name in ["Dashboard", "Keys", "Users", "Roles", "Commands", "Logs"]:
            ttk.Button(sidebar, text=name, command=lambda n=name: self.show_page(n)).pack(fill="x", pady=3)
            frame = ttk.Frame(self.page_stack)
            frame.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.pages[name] = frame

        self._build_dashboard_page(self.pages["Dashboard"])
        self._build_keys_page(self.pages["Keys"])
        self._build_users_page(self.pages["Users"])
        self._build_roles_page(self.pages["Roles"])
        self._build_commands_page(self.pages["Commands"])
        self._build_logs_page(self.pages["Logs"])
        self.show_page("Dashboard")

    def _build_dashboard_page(self, page):
        ttk.Label(page, text="Bot Token").pack(anchor="w")
        row = ttk.Frame(page)
        row.pack(fill="x", pady=4)
        self.token_entry = ttk.Entry(row, textvariable=self.token_var, show="*")
        self.token_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="👁", width=3, command=self.toggle_token).pack(side="left", padx=4)
        ttk.Button(row, text="Start", command=self.start_bot).pack(side="left", padx=4)
        ttk.Button(row, text="Emergency Lock", command=self.toggle_lock_mode).pack(side="left", padx=4)
        ttk.Label(page, textvariable=self.status_var).pack(anchor="w", pady=6)
        self.stats = ttk.Label(page, text="")
        self.stats.pack(anchor="w")

    def _build_keys_page(self, page):
        bar = ttk.Frame(page)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Entry(bar, textvariable=self.search_vars["keys"]).pack(side="left", fill="x", expand=True)
        ttk.Button(bar, text="Load Keys", command=self.load_keys_with_preview).pack(side="left", padx=4)
        ttk.Button(bar, text="Export Claims CSV", command=self.export_claims_csv).pack(side="left", padx=4)
        self.keys_list = tk.Listbox(page)
        self.keys_list.pack(fill="both", expand=True)

    def _build_users_page(self, page):
        top = ttk.Frame(page)
        top.pack(fill="x")
        self.user_input = tk.StringVar()
        ttk.Entry(top, textvariable=self.user_input).pack(side="left", fill="x", expand=True)
        ttk.Button(top, text="Add", command=self.add_user).pack(side="left", padx=4)
        ttk.Button(top, text="Import Users File", command=self.import_users_file).pack(side="left", padx=4)
        ttk.Button(top, text="Permission Test", command=self.permission_test).pack(side="left", padx=4)
        ttk.Entry(page, textvariable=self.search_vars["users"]).pack(fill="x", pady=4)
        self.users_list = tk.Listbox(page)
        self.users_list.pack(fill="both", expand=True)
        ttk.Label(page, text="Claimed users (click for history)").pack(anchor="w")
        ttk.Entry(page, textvariable=self.search_vars["claimed"]).pack(fill="x", pady=4)
        self.claimed_list = tk.Listbox(page)
        self.claimed_list.pack(fill="both", expand=True)
        self.claimed_list.bind("<<ListboxSelect>>", self.show_claimed_history)

    def _build_roles_page(self, page):
        self.guild_combo = ttk.Combobox(page, state="readonly")
        self.guild_combo.pack(fill="x")
        self.guild_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_roles())
        ttk.Entry(page, textvariable=self.search_vars["roles"]).pack(fill="x", pady=4)
        self.show_allowed_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(page, text="Only show allowed roles", variable=self.show_allowed_only, command=self.refresh_roles).pack(anchor="w")
        self.roles_list = tk.Listbox(page)
        self.roles_list.pack(fill="both", expand=True)

    def _build_commands_page(self, page):
        self.command_name = tk.StringVar()
        self.command_reply = tk.StringVar()
        ttk.Entry(page, textvariable=self.command_name).pack(fill="x")
        ttk.Entry(page, textvariable=self.command_reply).pack(fill="x", pady=4)
        ttk.Button(page, text="Save Command", command=self.save_command).pack(anchor="w")
        ttk.Entry(page, textvariable=self.search_vars["commands"]).pack(fill="x", pady=4)
        self.commands_list = tk.Listbox(page)
        self.commands_list.pack(fill="both", expand=True)

    def _build_logs_page(self, page):
        self.log_text = tk.Text(page, state="disabled")
        self.log_text.pack(fill="both", expand=True)

    def show_page(self, name):
        self.pages[name].tkraise()

    def toggle_token(self):
        self.token_entry.configure(show="" if self.token_entry.cget("show") == "*" else "*")

    def set_status(self, text):
        self.status_var.set(f"Status: {text}")

    def log(self, text: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.configure(state="disabled")
        self.log_text.see("end")
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(text + "\n")
        self.refresh_all()

    def auto_save(self):
        self.dist.save_state(str(AUTOSAVE_PATH))

    def refresh_all(self):
        query_keys = self.search_vars["keys"].get().lower()
        self.keys_list.delete(0, "end")
        for key in self.dist.keys:
            if query_keys in key.lower():
                self.keys_list.insert("end", f"{key[:5]}-*****-{key[-5:]}")

        query_users = self.search_vars["users"].get().lower()
        self.users_list.delete(0, "end")
        for uid in sorted(self.dist.allowed_users):
            label = f"{self.dist.username_cache.get(uid, 'Unknown')} ({uid})"
            if query_users in label.lower():
                self.users_list.insert("end", label)

        query_claimed = self.search_vars["claimed"].get().lower()
        self.claimed_list.delete(0, "end")
        for uid, keys in self.dist.claimed.items():
            label = f"{self.dist.username_cache.get(uid, 'Unknown')} ({uid}) - {len(keys)}"
            if query_claimed in label.lower():
                self.claimed_list.insert("end", label)

        self.commands_list.delete(0, "end")
        for k, v in self.dist.custom_commands.items():
            self.commands_list.insert("end", f"{k}: {v}")

        self.stats.configure(text=f"Remaining: {len(self.dist.keys)} | Allowed Users: {len(self.dist.allowed_users)} | Claimed: {sum(len(v) for v in self.dist.claimed.values())}")
        self.refresh_roles()

    def sync_guilds(self, snapshots):
        self.guild_data = {s.guild_name: s for s in snapshots}
        self.guild_combo["values"] = list(self.guild_data.keys())
        if snapshots and not self.guild_combo.get():
            self.guild_combo.set(snapshots[0].guild_name)
        self.refresh_roles()

    def refresh_roles(self):
        self.roles_list.delete(0, "end")
        selected = self.guild_combo.get()
        if selected not in self.guild_data:
            return
        snap = self.guild_data[selected]
        allowed = self.dist.server_settings[snap.guild_id].allowed_roles
        q = self.search_vars["roles"].get().lower()
        for role_id, name in snap.roles:
            if q and q not in name.lower():
                continue
            marker = "✅" if role_id in allowed else "❌"
            if self.show_allowed_only.get() and marker == "❌":
                continue
            self.roles_list.insert("end", f"{marker} {name} ({role_id})")

    def load_keys_with_preview(self):
        path = filedialog.askopenfilename(filetypes=[("Text", "*.txt")])
        if not path:
            return
        preview = self.dist.import_preview(path)
        self.log(f"[Info] Import preview total={preview['total_lines']} empty_removed={preview['empty_removed']} duplicates_removed={preview['duplicates_removed']} final={preview['final_count']}")
        self.dist.load_keys(preview["keys"])
        self.auto_save()
        self.refresh_all()

    def add_user(self):
        try:
            self.dist.allowed_users.add(int(self.user_input.get().strip()))
            self.auto_save()
            self.refresh_all()
        except ValueError:
            self.log("[Error] Invalid user ID")

    def import_users_file(self):
        path = filedialog.askopenfilename(filetypes=[("Text/CSV", "*.txt *.csv")])
        if not path:
            return
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        added, skipped = self.dist.load_allowed_users_from_lines(lines)
        self.log(f"[Success] Imported allowed users. added={added}, skipped={skipped}")
        self.auto_save()

    def show_claimed_history(self, _evt):
        sel = self.claimed_list.curselection()
        if not sel:
            return
        raw = self.claimed_list.get(sel[0])
        user_id = int(raw.split("(")[-1].split(")")[0])
        events = [e for e in self.dist.claim_history if e.user_id == user_id]
        self.log("[Info] Claim history for {}: {}".format(user_id, "; ".join([f"{e.key} @ {e.timestamp}" for e in events]) or "No history"))

    def permission_test(self):
        try:
            uid = int(self.user_input.get().strip())
        except ValueError:
            self.log("[Error] Enter user ID first")
            return
        selected = self.guild_combo.get()
        gid = self.guild_data[selected].guild_id if selected in self.guild_data else 0
        can, reason = self.dist.can_claim(uid, gid, [])
        self.log(f"[Info] Permission test for {uid}: {'Yes' if can else 'No'} - {reason}")

    def save_command(self):
        name = self.command_name.get().strip()
        if name:
            self.dist.custom_commands[name] = self.command_reply.get().strip()
            self.auto_save()
            self.refresh_all()

    def export_claims_csv(self):
        out = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not out:
            return
        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["User ID", "Username", "Key", "Date Claimed"])
            for e in self.dist.claim_history:
                w.writerow([e.user_id, e.username, e.key, e.timestamp])
        self.log(f"[Success] Exported claimed keys CSV to {out}")

    def start_bot(self):
        token = self.token_var.get().strip()
        if not token:
            self.log("[Error] Missing token")
            return
        self.controller.start(token, "!")

    def toggle_lock_mode(self):
        self.dist.lock_mode = not self.dist.lock_mode
        self.auto_save()
        self.log(f"[Warning] Emergency lock mode {'enabled' if self.dist.lock_mode else 'disabled'}")


def main():
    root = tk.Tk()
    Dashboard(root)
    root.mainloop()


if __name__ == "__main__":
    main()
