from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import queue
import re
import shutil
import shlex
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests


NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
DEFAULT_MODEL = "minimaxai/minimax-m3"
FALLBACK_MODEL = "meta/llama-3.1-70b-instruct"
ACTION_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```|(\{[\s\S]*?\"tool\"[\s\S]*?\})", re.DOTALL)

# Status HTTP yang boleh di-retry otomatis oleh client.
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
MAX_RETRIES = 3
ERROR_LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MiB


class AgentError(Exception):
    pass


class ModelError(AgentError):
    """Error dari model API, dengan kategori & indikasi apakah layak di-retry."""

    CATEGORIES = {
        "auth",          # 401/403
        "not_found",     # 404 model tidak ada
        "rate_limit",    # 429
        "server",        # 5xx
        "bad_request",   # 400/422
        "network",       # timeout / connection error
        "unknown",
    }

    def __init__(self, message: str, *, category: str = "unknown", status: int | None = None,
                 recoverable: bool = False, retry_after: float | None = None):
        super().__init__(message)
        self.category = category if category in self.CATEGORIES else "unknown"
        self.status = status
        self.recoverable = recoverable
        self.retry_after = retry_after


def terminal_width(default: int = 88) -> int:
    return max(48, min(shutil.get_terminal_size((default, 24)).columns, 120))


def supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def color(text: str, code: str) -> str:
    if not supports_color():
        return text
    return f"\033[{code}m{text}\033[0m"


def rule(title: str | None = None) -> str:
    width = terminal_width()
    if not title:
        return color("─" * width, "90")
    label = f" {title} "
    side = max(2, (width - len(label)) // 2)
    line = ("─" * side) + label + ("─" * max(2, width - side - len(label)))
    return color(line[:width], "90")


def compact_path(path: Path) -> str:
    text = str(path)
    home = str(Path.home())
    if text.startswith(home):
        text = "~" + text[len(home):]
    width = terminal_width()
    if len(text) <= width - 14:
        return text
    keep = width - 17
    return "..." + text[-keep:]


def print_header(model: str, workspace: Path, session_messages: int = 0) -> None:
    width = terminal_width()
    title = "Nexus CLI"
    print(rule())
    print(color(title, "1;36"))
    print(f"model     {model}")
    print(f"workspace {compact_path(workspace)}")
    print(f"session   {session_messages} messages")
    print(rule())
    hint = "Ketik /help untuk perintah, /exit untuk keluar."
    print(hint[:width])


def prompt_text() -> str:
    return color("nexus", "1;36") + color(" > ", "90")


def print_json_block(title: str, data: Any) -> None:
    print(rule(title))
    print(safe_json(data))


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def safe_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def wire_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


# Strip ANSI control sequences (CSI, OSC, simple escapes) and zero-width
# characters that often leak in via copy-paste from colored terminals or
# formatted web pages. Without this, the model receives literal escape
# bytes and may misbehave.
_ANSI_CSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_ANSI_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_ANSI_ESC_RE = re.compile(r"\x1b[@-_]")
_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u2028-\u202f\ufeff]")


def clean_input(text: str) -> str:
    """Remove ANSI escapes and zero-width chars from user input."""
    if not text:
        return text
    cleaned = _ANSI_OSC_RE.sub("", text)
    cleaned = _ANSI_CSI_RE.sub("", cleaned)
    cleaned = _ANSI_ESC_RE.sub("", cleaned)
    cleaned = _INVISIBLE_RE.sub("", cleaned)
    return cleaned


def truncate(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 14)] + "\n... (truncated)"


class Spinner:
    """Minimal rotating spinner that yields to the terminal while active."""

    FRAMES = ("\u280b", "\u2819", "\u2839", "\u2838", "\u283c", "\u2834", "\u2826", "\u2827", "\u2807", "\u280f")

    def __init__(self, label: str = "thinking"):
        self.label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "Spinner":
        if not sys.stdout.isatty():
            return self
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=1.0)
        sys.stdout.write("\r" + " " * (len(self.label) + 4) + "\r")
        sys.stdout.flush()

    def _run(self) -> None:
        idx = 0
        while not self._stop.is_set():
            frame = self.FRAMES[idx % len(self.FRAMES)]
            sys.stdout.write(f"\r{color(frame + ' ' + self.label, '90')} ")
            sys.stdout.flush()
            idx += 1
            self._stop.wait(0.08)


class Workspace:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        # State (memory, session, skills, mcp config) disimpan di dalam workspace
        # agar tiap proyek punya history sendiri. Path disimpan sebagai string
        # absolut agar tidak ambigu jika proses berganti cwd.
        self.state_dir = (self.root / ".nexus").resolve()
        try:
            self.state_dir.mkdir(exist_ok=True)
            self._writable = True
        except OSError:
            # Fallback ke ~/.config/nexus-cli/<hash> kalau workspace read-only.
            fallback = Path.home() / ".config" / "nexus-cli" / self._fingerprint()
            fallback.mkdir(parents=True, exist_ok=True)
            self.state_dir = fallback
            self._writable = True

    def _fingerprint(self) -> str:
        import hashlib
        return hashlib.sha1(str(self.root).encode("utf-8")).hexdigest()[:16]

    def resolve(self, raw: str | Path) -> Path:
        candidate = (self.root / raw).expanduser().resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise AgentError(f"path keluar workspace: {raw}") from exc
        return candidate

    def rel(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.root))


class MemoryStore:
    def __init__(self, path: Path):
        self.path = path
        self.items: list[dict[str, Any]] = []
        self.load()

    def load(self) -> None:
        if self.path.exists():
            self.items = json.loads(self.path.read_text(encoding="utf-8") or "[]")

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(safe_json(self.items) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    def add(self, text: str) -> dict[str, Any]:
        item = {"time": int(time.time()), "text": text}
        self.items.append(item)
        self.save()
        return item

    def prompt_text(self) -> str:
        if not self.items:
            return "Tidak ada memori tersimpan."
        recent = self.items[-20:]
        return "\n".join(f"- {item['text']}" for item in recent)


class ErrorLog:
    """Append-only log error ke .nexus/errors.jsonl dengan rotasi sederhana."""

    def __init__(self, path: Path, max_bytes: int = ERROR_LOG_MAX_BYTES):
        self.path = path
        self.max_bytes = max_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, *, category: str, status: int | None, message: str,
               model: str | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        entry = {
            "time": int(time.time()),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "category": category,
            "status": status,
            "model": model,
            "message": message[:1000],
            "extra": extra or {},
        }
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass  # logging tidak boleh menggangu alur utama
        self._rotate_if_needed()
        return entry

    def _rotate_if_needed(self) -> None:
        try:
            if self.path.exists() and self.path.stat().st_size > self.max_bytes:
                # Rotasi: rename ke .1, mulai ulang. Simpan 1 arsip saja.
                backup = self.path.with_suffix(self.path.suffix + ".1")
                if backup.exists():
                    backup.unlink()
                self.path.rename(backup)
        except OSError:
            pass

    def tail(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        entries = []
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    def clear(self) -> None:
        for suffix in ("", ".1"):
            target = self.path.with_suffix(self.path.suffix + suffix) if suffix else self.path
            if target.exists():
                try:
                    target.unlink()
                except OSError:
                    pass


class SessionStore:
    def __init__(self, path: Path, max_messages: int = 80):
        self.path = path
        self.max_messages = max_messages
        self.messages: list[dict[str, Any]] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        messages = raw.get("messages", [])
        if isinstance(messages, list):
            self.messages = [msg for msg in messages if self._valid_message(msg)][-self.max_messages :]

    def save(self, messages: list[dict[str, Any]] | None = None) -> None:
        if messages is not None:
            self.messages = [self._clean_message(msg) for msg in messages if self._valid_message(msg)]
        self.messages = self.messages[-self.max_messages :]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"updated_at": int(time.time()), "messages": self.messages}
        # Atomic write: tulis ke .tmp lalu rename, supaya tidak korup
        # jika proses mati mendadak (Ctrl+C / crash / power loss).
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(safe_json(payload) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    def clear(self) -> None:
        self.messages = []
        if self.path.exists():
            self.path.unlink()

    def summary(self, limit: int = 12) -> list[dict[str, str]]:
        rows = []
        for msg in self.messages[-limit:]:
            content = msg.get("content", "")
            if not isinstance(content, str):
                content = "[multimodal content]"
            rows.append({"role": str(msg.get("role", "")), "content": truncate(content.replace("\n", " "), 180)})
        return rows

    @staticmethod
    def _valid_message(msg: Any) -> bool:
        return isinstance(msg, dict) and msg.get("role") in {"user", "assistant"} and "content" in msg

    @staticmethod
    def _clean_message(msg: dict[str, Any]) -> dict[str, Any]:
        role = str(msg.get("role", "user"))
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = []
            media_count = 0
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(str(part.get("text", "")))
                else:
                    media_count += 1
            suffix = f"\n[media omitted: {media_count} item]" if media_count else ""
            content = "\n".join(text_parts) + suffix
        elif not isinstance(content, str):
            content = str(content)
        return {"role": role, "content": content}


class SkillStore:
    def __init__(self, directories: list[Path]):
        self.directories = directories

    def list(self) -> list[dict[str, str]]:
        skills = []
        seen: set[Path] = set()
        for directory in self.directories:
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.md")):
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                text = path.read_text(encoding="utf-8", errors="replace")
                title = next((line.lstrip("# ").strip() for line in text.splitlines() if line.strip()), path.stem)
                skills.append({"name": path.stem, "title": title, "path": str(path)})
        return skills

    def prompt_text(self) -> str:
        chunks = []
        for skill in self.list():
            path = Path(skill["path"])
            chunks.append(f"## Skill: {path.stem}\n{path.read_text(encoding='utf-8', errors='replace')}")
        return "\n\n".join(chunks) if chunks else "Tidak ada skill lokal."


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: list[str]
    env: dict[str, str]


class MCPClient:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self.config_path = workspace.state_dir / "mcp.json"
        self.processes: dict[str, subprocess.Popen[str]] = {}
        self.readers: dict[str, queue.Queue[str]] = {}
        self.next_id = 1

    def configs(self) -> dict[str, MCPServerConfig]:
        if not self.config_path.exists():
            return {}
        raw = json.loads(self.config_path.read_text(encoding="utf-8") or "{}")
        servers = raw.get("servers", {})
        configs = {}
        for name, cfg in servers.items():
            configs[name] = MCPServerConfig(
                name=name,
                command=cfg["command"],
                args=list(cfg.get("args", [])),
                env={str(k): str(v) for k, v in cfg.get("env", {}).items()},
            )
        return configs

    def list_servers(self) -> list[dict[str, Any]]:
        return [
            {"name": cfg.name, "command": cfg.command, "args": cfg.args, "running": cfg.name in self.processes}
            for cfg in self.configs().values()
        ]

    def _reader(self, name: str, proc: subprocess.Popen[str]) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            self.readers[name].put(line)

    def start(self, name: str) -> None:
        if name in self.processes:
            return
        configs = self.configs()
        if name not in configs:
            raise AgentError(f"MCP server tidak ditemukan: {name}")
        cfg = configs[name]
        env = os.environ.copy()
        env.update(cfg.env)
        proc = subprocess.Popen(
            [cfg.command, *cfg.args],
            cwd=str(self.workspace.root),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.processes[name] = proc
        self.readers[name] = queue.Queue()
        threading.Thread(target=self._reader, args=(name, proc), daemon=True).start()
        self.request(name, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "nexus-cli", "version": "0.1.0"}})
        self.notify(name, "notifications/initialized", {})

    def notify(self, name: str, method: str, params: dict[str, Any]) -> None:
        proc = self.processes[name]
        assert proc.stdin is not None
        proc.stdin.write(wire_json({"jsonrpc": "2.0", "method": method, "params": params}) + "\n")
        proc.stdin.flush()

    def request(self, name: str, method: str, params: dict[str, Any] | None = None, timeout: float = 10.0) -> Any:
        self.start(name) if name not in self.processes else None
        req_id = self.next_id
        self.next_id += 1
        proc = self.processes[name]
        assert proc.stdin is not None
        proc.stdin.write(wire_json({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}) + "\n")
        proc.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                line = self.readers[name].get(timeout=0.2)
            except queue.Empty:
                if proc.poll() is not None:
                    raise AgentError(f"MCP server berhenti: {name}")
                continue
            msg = json.loads(line)
            if msg.get("id") == req_id:
                if "error" in msg:
                    raise AgentError(safe_json(msg["error"]))
                return msg.get("result")
        raise AgentError(f"timeout MCP {name}.{method}")

    def list_tools(self, server: str) -> Any:
        return self.request(server, "tools/list")

    def call_tool(self, server: str, tool: str, arguments: dict[str, Any]) -> Any:
        return self.request(server, "tools/call", {"name": tool, "arguments": arguments}, timeout=30.0)

    def close(self) -> None:
        for proc in self.processes.values():
            proc.terminate()


class ToolRegistry:
    def __init__(self, workspace: Workspace, memory: MemoryStore, skills: SkillStore, mcp: MCPClient):
        self.workspace = workspace
        self.memory = memory
        self.skills = skills
        self.mcp = mcp
        self.tools: dict[str, Callable[[dict[str, Any]], Any]] = {
            "list_files": self.list_files,
            "read_file": self.read_file,
            "write_file": self.write_file,
            "append_file": self.append_file,
            "replace_in_file": self.replace_in_file,
            "search_text": self.search_text,
            "shell_command": self.shell_command,
            "open_browser": self.open_browser,
            "remember": self.remember,
            "list_skills": lambda args: self.skills.list(),
            "mcp_list_servers": lambda args: self.mcp.list_servers(),
            "mcp_list_tools": lambda args: self.mcp.list_tools(args["server"]),
            "mcp_call_tool": lambda args: self.mcp.call_tool(args["server"], args["tool"], args.get("arguments", {})),
        }

    def describe(self) -> str:
        return "\n".join(
            [
                '- list_files {"path":".","max_depth":3}',
                '- read_file {"path":"file"}',
                '- write_file {"path":"file","content":"..."}',
                '- append_file {"path":"file","content":"..."}',
                '- replace_in_file {"path":"file","old":"...","new":"..."}',
                '- search_text {"pattern":"...","path":"."}',
                '- shell_command {"command":"npm test","timeout":120}',
                '- open_browser {"url":"http://localhost:3000"}',
                '- remember {"text":"..."}',
                '- list_skills {}',
                '- mcp_list_servers {}',
                '- mcp_list_tools {"server":"name"}',
                '- mcp_call_tool {"server":"name","tool":"name","arguments":{}}',
            ]
        )

    def call(self, name: str, args: dict[str, Any]) -> Any:
        if name not in self.tools:
            raise AgentError(f"tool tidak dikenal: {name}")
        return self.tools[name](args)

    def list_files(self, args: dict[str, Any]) -> list[str]:
        base = self.workspace.resolve(args.get("path", "."))
        max_depth = int(args.get("max_depth", 3))
        result = []
        for path in sorted(base.rglob("*")):
            if ".git" in path.parts or ".nexus" in path.parts:
                continue
            depth = len(path.relative_to(base).parts)
            if depth > max_depth:
                continue
            result.append(self.workspace.rel(path) + ("/" if path.is_dir() else ""))
            if len(result) >= 500:
                break
        return result

    def read_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self.workspace.resolve(args["path"])
        limit = int(args.get("limit", 20000))
        text = path.read_text(encoding="utf-8", errors="replace")
        return {"path": self.workspace.rel(path), "content": text[:limit], "truncated": len(text) > limit}

    def write_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self.workspace.resolve(args["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args.get("content", ""), encoding="utf-8")
        return {"path": self.workspace.rel(path), "bytes": path.stat().st_size}

    def append_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self.workspace.resolve(args["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(args.get("content", ""))
        return {"path": self.workspace.rel(path), "bytes": path.stat().st_size}

    def replace_in_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self.workspace.resolve(args["path"])
        text = path.read_text(encoding="utf-8", errors="replace")
        old = args["old"]
        new = args["new"]
        count = text.count(old)
        if count == 0:
            raise AgentError("teks lama tidak ditemukan")
        path.write_text(text.replace(old, new, int(args.get("count", -1))), encoding="utf-8")
        return {"path": self.workspace.rel(path), "replacements": count}

    def search_text(self, args: dict[str, Any]) -> str:
        base = self.workspace.resolve(args.get("path", "."))
        pattern = args["pattern"]
        cmd = ["rg", "--line-number", "--hidden", "-g", "!.git", "-g", "!.nexus", pattern, str(base)]
        try:
            proc = subprocess.run(cmd, cwd=str(self.workspace.root), text=True, capture_output=True, timeout=20)
        except FileNotFoundError:
            cmd = ["grep", "-RIn", pattern, str(base)]
            proc = subprocess.run(cmd, cwd=str(self.workspace.root), text=True, capture_output=True, timeout=20)
        output = proc.stdout or proc.stderr
        return output[:20000]

    def remember(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.memory.add(args["text"])

    def shell_command(self, args: dict[str, Any]) -> dict[str, Any]:
        command = str(args["command"]).strip()
        timeout = int(args.get("timeout", 60))
        if not command:
            raise AgentError("command kosong")
        blocked = [
            "rm -rf /",
            "rm -rf ~",
            "mkfs",
            "dd if=",
            "shutdown",
            "reboot",
            "git reset --hard",
            "git clean -fd",
            "chmod -R 777 /",
        ]
        lowered = command.lower()
        if any(item in lowered for item in blocked):
            raise AgentError(f"command diblokir karena berisiko destruktif: {command}")
        proc = subprocess.run(
            command,
            cwd=str(self.workspace.root),
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        return {
            "command": command,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-20000:],
            "stderr": proc.stderr[-20000:],
        }

    def open_browser(self, args: dict[str, Any]) -> dict[str, Any]:
        target = str(args["url"]).strip()
        if not target:
            raise AgentError("url kosong")
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
            target = self.workspace.resolve(target).as_uri()
        opened = webbrowser.open(target)
        return {"url": target, "opened": opened}


class NvidiaClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float,
        top_p: float,
        max_tokens: int,
        *,
        error_log: ErrorLog | None = None,
        fallback_model: str | None = FALLBACK_MODEL,
        max_retries: int = MAX_RETRIES,
    ):
        self.api_key = api_key
        self.model = model
        self.fallback_model = fallback_model if fallback_model and fallback_model != model else None
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        self.error_log = error_log
        self.max_retries = max_retries

    # -- public API --
    def chat(self, messages: list[dict[str, Any]], stream: bool = True) -> str:
        try:
            return self._chat_with_resilience(messages, stream=stream, attempted_fallback=False)
        except ModelError as exc:
            # Kalau error recoverable dan model fallback tersedia, otomatis
            # coba fallback sebelum menyerah. Berlaku untuk rate_limit,
            # server, network, dan not_found.
            if (
                exc.recoverable
                and self.fallback_model
                and exc.category in {"server", "rate_limit", "network", "not_found"}
            ):
                self._log(exc, attempted_fallback=False, fallback_triggered=True)
                previous = self.model
                self.model = self.fallback_model
                print(f"\n[nexus] {exc.category} pada '{previous}', fallback ke '{self.fallback_model}'.")
                try:
                    return self._chat_with_resilience(messages, stream=stream, attempted_fallback=True)
                finally:
                    self.model = previous
            # _chat_with_resilience sudah mencatat error ini; tidak perlu log lagi.
            raise

    # -- internal --
    def _log(self, exc: ModelError, *, attempted_fallback: bool, fallback_triggered: bool) -> None:
        if not self.error_log:
            return
        self.error_log.record(
            category=exc.category,
            status=exc.status,
            message=str(exc),
            model=self.model,
            extra={
                "recoverable": exc.recoverable,
                "retry_after": exc.retry_after,
                "attempted_fallback": attempted_fallback,
                "fallback_triggered": fallback_triggered,
            },
        )

    def _categorize(self, status: int) -> tuple[str, bool]:
        if status in (401, 403):
            return "auth", False
        if status == 404:
            return "not_found", True  # bisa di-fallback ke model lain
        if status == 429:
            return "rate_limit", True
        if 500 <= status <= 599:
            return "server", True
        if status in (400, 408, 422):
            return "bad_request", False
        return "unknown", False

    def _chat_with_resilience(self, messages: list[dict[str, Any]], *, stream: bool, attempted_fallback: bool) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "text/event-stream" if stream else "application/json",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "stream": stream,
            "chat_template_kwargs": {"thinking_mode": "disabled"},
        }
        last_exc: ModelError | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return self._do_request(headers, payload, stream=stream)
            except ModelError as exc:
                last_exc = exc
                # Log hanya saat attempt terakhir atau non-retryable; kalau
                # retry, kita log sekali saja di akhir agar tidak spam.
                # Untuk kesederhanaan: log di setiap percobaan.
                self._log(exc, attempted_fallback=attempted_fallback, fallback_triggered=False)
                # not_found: retry pada model yang sama percuma, langsung naik.
                if exc.category == "not_found":
                    raise
                if not exc.recoverable or attempt >= self.max_retries:
                    raise
                wait = exc.retry_after or min(2 ** attempt, 8)
                # Server 429/5xx biasanya sudah pre-jitter dengan retry_after
                # dari header; kalau tidak ada, exponential backoff capped.
                print(f"\n[nexus] {exc.category} (percobaan {attempt}/{self.max_retries}), retry dalam {wait:.1f}s...")
                time.sleep(wait)
            except requests.exceptions.RequestException as exc:
                last_exc = ModelError(
                    f"Gagal menghubungi NVIDIA API: {exc}",
                    category="network",
                    recoverable=True,
                )
                self._log(last_exc, attempted_fallback=attempted_fallback, fallback_triggered=False)
                if attempt >= self.max_retries:
                    raise last_exc from exc
                wait = min(2 ** attempt, 8)
                print(f"\n[nexus] network error (percobaan {attempt}/{self.max_retries}), retry dalam {wait:.1f}s...")
                time.sleep(wait)
        # Seharusnya tidak pernah sampai sini, tapi untuk type-checker:
        if last_exc is not None:
            raise last_exc
        raise ModelError("retry loop berakhir tanpa respons", category="unknown")

    def _do_request(self, headers: dict[str, str], payload: dict[str, Any], *, stream: bool) -> str:
        try:
            response = requests.post(NVIDIA_URL, headers=headers, json=payload, stream=stream, timeout=120)
        except requests.exceptions.RequestException as exc:
            # network/timeout -> dibiarkan naik ke caller (kategori network, recoverable)
            raise

        if response.status_code >= 400:
            category, recoverable = self._categorize(response.status_code)
            retry_after_raw = response.headers.get("retry-after")
            retry_after: float | None = None
            if retry_after_raw:
                try:
                    retry_after = float(retry_after_raw)
                except ValueError:
                    retry_after = None
            detail = (response.text or "").strip()[:500]
            msg = f"NVIDIA API error HTTP {response.status_code}: {detail}"
            raise ModelError(
                msg,
                category=category,
                status=response.status_code,
                recoverable=recoverable,
                retry_after=retry_after,
            )

        if not stream:
            data = response.json()
            return data["choices"][0]["message"]["content"]

        chunks: list[str] = []
        for line in response.iter_lines():
            if not line:
                continue
            decoded = line.decode("utf-8")
            if decoded.startswith("data: "):
                decoded = decoded[6:]
            if decoded.strip() == "[DONE]":
                break
            try:
                data = json.loads(decoded)
            except json.JSONDecodeError:
                continue
            delta = data.get("choices", [{}])[0].get("delta", {})
            text = delta.get("content") or ""
            if text:
                print(text, end="", flush=True)
                chunks.append(text)
        print()
        return "".join(chunks)


def system_prompt(workspace: Workspace, tools: ToolRegistry, memory: MemoryStore, skills: SkillStore,
                   errors: ErrorLog | None = None) -> str:
    recent_errors = errors.tail(5) if errors else []
    error_block = ""
    if recent_errors:
        bullets = []
        for entry in recent_errors:
            ts = entry.get("iso", entry.get("time", ""))
            cat = entry.get("category", "unknown")
            msg = entry.get("message", "")[:200]
            bullets.append(f"- [{ts}] {cat}: {msg}")
        error_block = "\nError terbaru (untuk diagnosa):\n" + "\n".join(bullets)
    return f"""Anda adalah Nexus CLI, coding agent terminal pragmatis.
Jawab dalam bahasa pengguna. Bekerja di workspace: {workspace.root}

Aturan:
- Jangan mengarang isi file. Gunakan tool read_file/list_files/search_text saat perlu konteks.
- Untuk mengubah file, panggil write_file, append_file, atau replace_in_file.
- Untuk menjalankan terminal, gunakan shell_command di workspace.
- Untuk membuka browser atau file HTML, gunakan open_browser.
- Jika perlu beberapa langkah, panggil satu tool dulu, tunggu hasilnya, lalu lanjut.
- Setelah tugas selesai, beri ringkasan singkat dan sebut file yang diubah.
- Tool call harus berupa satu JSON object valid, boleh di dalam fenced code block.
- Format tool call: {{"tool":"read_file","args":{{"path":"README.md"}}}}

Tool tersedia:
{tools.describe()}

Memori:
{memory.prompt_text()}

Skills lokal:
{skills.prompt_text()}
{error_block}
"""


def extract_action(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    seen: set[str] = set()
    candidates = [match.group(1) or match.group(2) for match in ACTION_RE.finditer(text)]
    candidates.append(text)
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            for index, char in enumerate(candidate):
                if char != "{":
                    continue
                try:
                    data, _ = decoder.raw_decode(candidate[index:])
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict) and "tool" in data:
                    return data
            continue
        if isinstance(data, dict) and "tool" in data:
            return data
    return None


def media_part(value: str, workspace: Workspace) -> dict[str, Any]:
    if value.startswith(("http://", "https://", "data:")):
        url = value
    else:
        path = workspace.resolve(value)
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        url = f"data:{mime};base64,{b64}"
    mime_group = url.split(":", 1)[1].split("/", 1)[0] if url.startswith("data:") else ""
    if any(value.lower().endswith(ext) for ext in [".mp4", ".mov", ".webm", ".mkv"]) or mime_group == "video":
        return {"type": "video_url", "video_url": {"url": url}}
    return {"type": "image_url", "image_url": {"url": url}}


class NexusAgent:
    def __init__(self, client: NvidiaClient, workspace: Workspace, global_config: Path, stream: bool = True):
        self.workspace = workspace
        self.memory = MemoryStore(workspace.state_dir / "memory.json")
        self.session = SessionStore(workspace.state_dir / "session.json")
        self.errors = ErrorLog(workspace.state_dir / "errors.jsonl")
        self.skills = SkillStore([global_config / "skills", workspace.state_dir / "skills"])
        self.mcp = MCPClient(workspace)
        self.tools = ToolRegistry(workspace, self.memory, self.skills, self.mcp)
        self.client = client
        self.stream = stream
        self.messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt(workspace, self.tools, self.memory, self.skills, self.errors)},
            *self.session.messages,
        ]

    def refresh_system(self) -> None:
        self.messages[0] = {"role": "system", "content": system_prompt(self.workspace, self.tools, self.memory, self.skills, self.errors)}

    def save_session(self) -> None:
        """Persist session non-system ke disk. Aman dipanggil berulang."""
        try:
            self.session.save([msg for msg in self.messages if msg.get("role") != "system"])
        except Exception as exc:  # noqa: BLE001
            # Log ke error log agar masalah session-persistence tidak hilang.
            try:
                self.errors.record(
                    category="session_save",
                    status=None,
                    message=f"gagal menyimpan session: {exc}",
                    model=getattr(self.client, "model", None),
                )
            except Exception:
                pass
            print(f"Peringatan: gagal menyimpan session: {exc}")

    def ask(self, user_text: str, media: list[str] | None = None) -> None:
        self.refresh_system()
        if media:
            content = [{"type": "text", "text": user_text}]
            content.extend(media_part(item, self.workspace) for item in media)
            self.messages.append({"role": "user", "content": content})
        else:
            self.messages.append({"role": "user", "content": user_text})
        # Simpan segera setelah input user diterima, agar tidak hilang
        # kalau model timeout/error atau user menekan Ctrl+C di tengah jalan.
        self.save_session()
        try:
            for _ in range(8):
                try:
                    assistant = self.client.chat(self.messages, stream=self.stream)
                except ModelError as exc:
                    print(f"\nError model: {exc}")
                    return
                if not self.stream:
                    print(assistant)
                self.messages.append({"role": "assistant", "content": assistant})
                self.save_session()
                action = extract_action(assistant)
                if not action:
                    return
                name = action["tool"]
                args = action.get("args", {})
                print_json_block(f"tool: {name}", args)
                try:
                    result = self.tools.call(name, args)
                    payload = {"ok": True, "tool": name, "result": result}
                except Exception as exc:  # noqa: BLE001 - CLI must return tool failures to model.
                    payload = {"ok": False, "tool": name, "error": str(exc)}
                print_json_block("result", payload)
                self.messages.append({"role": "user", "content": "Hasil tool:\n" + safe_json(payload)})
                self.save_session()
            print(rule("limit"))
            print("Batas langkah agent tercapai. Jalankan prompt lanjutan jika masih perlu.")
        finally:
            # Jaminan terakhir: session selalu tersimpan saat ask() keluar,
            # baik normal, exception, maupun KeyboardInterrupt.
            self.save_session()

    def close(self) -> None:
        self.mcp.close()


def multiline_input(prompt: str = "Masukkan teks, akhiri dengan baris tunggal EOF:") -> str:
    print(prompt)
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == "EOF":
            break
        lines.append(line)
    return "\n".join(lines) + ("\n" if lines else "")


def run_command(agent: NexusAgent, line: str) -> bool:
    parts = shlex.split(line)
    if not parts:
        return True
    cmd = parts[0]
    try:
        if cmd in {"/exit", "/quit"}:
            return False
        if cmd == "/help":
            print(rule("help"))
            print("/help                         tampilkan bantuan")
            print("/status                       info workspace, memory, skill, MCP")
            print("/read PATH                    baca file")
            print("/write PATH                   tulis file, akhiri input dengan EOF")
            print("/append PATH                  tambah isi file, akhiri input dengan EOF")
            print("/search PATTERN               cari teks di workspace")
            print("/run COMMAND                  jalankan command terminal")
            print("/open URL_OR_PATH             buka browser")
            print("/image PATH_OR_URL PROMPT     kirim gambar/video ke model")
            print("/remember TEXT                simpan memory")
            print("/session                      lihat riwayat session aktif")
            print("/clear-session                hapus riwayat session project")
            print("/memory | /skills | /mcp      lihat state agent")
            print("/errors [N]                   lihat N error terakhir (default 20)")
            print("/clear-errors                 hapus log error")
            print("/exit                         keluar")
        elif cmd == "/status":
            print_json_block(
                "status",
                {
                    "workspace": str(agent.workspace.root),
                    "model": agent.client.model,
                    "fallback_model": agent.client.fallback_model,
                    "session_file": str(agent.session.path),
                    "session_messages": len(agent.session.messages),
                    "memory_file": str(agent.memory.path),
                    "memory_items": len(agent.memory.items),
                    "errors_file": str(agent.errors.path),
                    "recent_errors": len(agent.errors.tail(5)),
                    "skills": agent.skills.list(),
                    "mcp": agent.mcp.list_servers(),
                },
            )
        elif cmd == "/read":
            print(agent.tools.read_file({"path": parts[1]})["content"])
        elif cmd == "/write":
            content = multiline_input()
            print_json_block("write", agent.tools.write_file({"path": parts[1], "content": content}))
        elif cmd == "/append":
            content = multiline_input()
            print_json_block("append", agent.tools.append_file({"path": parts[1], "content": content}))
        elif cmd == "/search":
            print(agent.tools.search_text({"pattern": " ".join(parts[1:])}))
        elif cmd == "/run":
            print_json_block("run", agent.tools.shell_command({"command": " ".join(parts[1:])}))
        elif cmd == "/open":
            print_json_block("open", agent.tools.open_browser({"url": parts[1]}))
        elif cmd == "/image":
            if len(parts) < 3:
                print("Usage: /image PATH_OR_URL PROMPT")
            else:
                agent.ask(" ".join(parts[2:]), media=[parts[1]])
        elif cmd == "/remember":
            print_json_block("remember", agent.tools.remember({"text": " ".join(parts[1:])}))
        elif cmd == "/memory":
            print_json_block("memory", agent.memory.items)
        elif cmd == "/session":
            print_json_block("session", agent.session.summary())
        elif cmd == "/clear-session":
            agent.session.clear()
            agent.messages = [agent.messages[0]]
            print("Session project sudah dihapus.")
        elif cmd == "/skills":
            print_json_block("skills", agent.skills.list())
        elif cmd == "/mcp":
            print_json_block("mcp", agent.mcp.list_servers())
        elif cmd == "/errors":
            limit = 20
            if len(parts) >= 2:
                try:
                    limit = max(1, min(int(parts[1]), 200))
                except ValueError:
                    print("Usage: /errors [N]")
                    return True
            entries = agent.errors.tail(limit)
            if not entries:
                print("Tidak ada error tercatat.")
            else:
                print_json_block(f"errors (terakhir {len(entries)})", entries)
        elif cmd == "/clear-errors":
            agent.errors.clear()
            print("Log error sudah dihapus.")
        else:
            print("Perintah tidak dikenal. Ketik /help.")
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}")
    return True


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Nexus CLI coding agent powered by NVIDIA MiniMax-M3.")
    parser.add_argument("--workspace", default=".", help="Direktori kerja yang boleh diakses agent.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--no-stream", action="store_true")
    parser.add_argument("--image", action="append", default=[], help="Path/URL gambar atau video untuk prompt sekali jalan.")
    parser.add_argument("prompt", nargs="*", help="Prompt sekali jalan. Jika kosong, masuk mode interaktif.")
    args = parser.parse_args(argv)

    workspace = Workspace(Path(args.workspace))
    global_config = Path.home() / ".config" / "nexus-cli"
    load_env_file(global_config / ".env")
    load_env_file(Path.cwd() / ".env")
    load_env_file(workspace.root / ".env")
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        print(
            "NVIDIA_API_KEY belum diset. Isi ~/.config/nexus-cli/.env, .env proyek, atau export environment variable.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    error_log = ErrorLog(workspace.state_dir / "errors.jsonl")
    client = NvidiaClient(
        api_key,
        args.model,
        args.temperature,
        args.top_p,
        args.max_tokens,
        error_log=error_log,
        fallback_model=os.environ.get("NEXUS_FALLBACK_MODEL", FALLBACK_MODEL),
    )
    agent = NexusAgent(client, workspace, global_config=global_config, stream=not args.no_stream)
    # Pakai log instance yang sama agar konsisten dengan /errors command.
    agent.errors = error_log
    agent.client.error_log = error_log
    exit_reason = "selesai"
    try:
        if args.prompt:
            agent.ask(" ".join(args.prompt), media=args.image)
            return
        print_header(args.model, workspace.root, len(agent.session.messages))
        while True:
            try:
                line = input("\n" + prompt_text()).strip()
            except EOFError:
                print()
                exit_reason = "EOF"
                break
            except KeyboardInterrupt:
                print()
                exit_reason = "Ctrl+C"
                break
            if not line:
                continue
            if line.startswith("/"):
                if not run_command(agent, line):
                    exit_reason = "/exit"
                    break
            else:
                try:
                    agent.ask(line)
                except KeyboardInterrupt:
                    print()
                    exit_reason = "Ctrl+C"
                    break
    finally:
        # Pastikan session dan memory tersimpan sebelum proses benar-benar keluar.
        try:
            agent.save_session()
        except Exception:
            pass
        try:
            agent.close()
        except Exception:
            pass
        if exit_reason != "selesai":
            saved = len(agent.session.messages)
            print(rule("bye"))
            print(f"Session tersimpan: {saved} pesan -> {agent.session.path}")


if __name__ == "__main__":
    main()
