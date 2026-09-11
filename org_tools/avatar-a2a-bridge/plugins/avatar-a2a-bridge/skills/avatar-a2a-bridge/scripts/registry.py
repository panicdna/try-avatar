"""Shared local discovery registry for avatar-a2a-bridge.

Same-machine, multi-Claude-Code-session prototype (see
docs/superpowers/specs/2026-09-12-avatar-a2a-bridge-design.md): there is no
DNS to publish an Agent Card at, so `serve.py` writes its port + a path to a
per-avatar bearer token into this file, and `call.py` reads it back by name.

Layout under ~/.a2a-avatars/ (override with $A2A_AVATARS_DIR):
  registry.json        {"<avatar-name>": {port, url, token_file, pid, pid_ns, started_at}}
  tokens/<name>.token   random secret, chmod 600, read by call.py to authenticate

`token_file` is recorded relative to the registry directory, so one directory
shared between WSL and Windows on the same PC (each side pointing
$A2A_AVATARS_DIR at it, e.g. /mnt/c/x and C:\\x) resolves the token from
either side, whose absolute path syntax for it differs.

Entries whose `pid` is no longer alive are treated as stale and dropped
whenever the registry is read (serve.py died without a clean SIGTERM/SIGINT
exit, e.g. SIGKILL or a crash) -- the file never needs manual cleanup. That
check only applies to entries registered from this process's own pid space
(`pid_ns`): a WSL pid means nothing to a Windows process and vice versa, so
entries from the other side are kept and left for that side to prune. They
are deliberately NOT pruned on a failed HTTP check either: under WSL2 NAT a
live Windows server is usually unreachable from WSL, and pruning it there
would delete a working entry for every reader.
"""
import json
import os
import secrets
import time
import urllib.request
from pathlib import Path

REGISTRY_DIR = Path(os.environ.get("A2A_AVATARS_DIR", str(Path.home() / ".a2a-avatars")))
REGISTRY_FILE = REGISTRY_DIR / "registry.json"
TOKENS_DIR = REGISTRY_DIR / "tokens"
AGENT_CARD_PATH = "/.well-known/agent-card.json"  # kept in sync with serve.py


def _ensure_dirs() -> None:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    for d in (REGISTRY_DIR, TOKENS_DIR):
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass


def _load_raw() -> dict:
    _ensure_dirs()
    if not REGISTRY_FILE.exists():
        return {}
    try:
        return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    _ensure_dirs()
    tmp = REGISTRY_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(REGISTRY_FILE)


def pid_namespace() -> str:
    """Identifies the pid space this process lives in; an entry's pid can only
    be checked from the same one."""
    if os.name == "nt":
        return "windows"
    try:
        return "linux:" + os.readlink("/proc/self/ns/pid")
    except OSError:
        return "posix"


def is_local(entry: dict) -> bool:
    # Entries from before pid_ns was recorded are assumed local (the old behavior).
    return entry.get("pid_ns", pid_namespace()) == pid_namespace()


def _is_alive_windows(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    ERROR_ACCESS_DENIED = 5
    STILL_ACTIVE = 259

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Access denied means the process exists but belongs to someone else.
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    # On Windows os.kill(pid, 0) is not a liveness probe: 0 == CTRL_C_EVENT, so
    # it sends a console Ctrl+C (or fails for a process on another console).
    if os.name == "nt":
        return _is_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def probe(name: str, entry: dict, timeout: float = 2.0) -> bool:
    """True if `entry`'s URL serves an Agent Card named `name`. For display
    only, never for pruning (see module docstring)."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # loopback: bypass any proxy
    try:
        with opener.open(entry["url"].rstrip("/") + AGENT_CARD_PATH, timeout=timeout) as resp:
            return json.loads(resp.read()).get("name") == name
    except (OSError, ValueError, KeyError, AttributeError):
        return False


def _prune(data: dict) -> tuple[dict, bool]:
    pruned = {name: e for name, e in data.items() if not is_local(e) or is_alive(e.get("pid", -1))}
    return pruned, pruned.keys() != data.keys()


def load() -> dict:
    """All live entries. Persists the prune if any dead entries were dropped."""
    data = _load_raw()
    pruned, changed = _prune(data)
    if changed:
        _save(pruned)
    return pruned


def token_ref(name: str) -> str:
    """The `token_file` value to record for `name`: relative to REGISTRY_DIR,
    with forward slashes, so it resolves from WSL and Windows alike."""
    return f"tokens/{name}.token"


def new_token(name: str) -> str:
    """Generate and store a fresh bearer token for `name`; returns the token."""
    _ensure_dirs()
    token = secrets.token_urlsafe(32)
    path = REGISTRY_DIR / token_ref(name)
    path.write_text(token, encoding="utf-8")
    os.chmod(path, 0o600)
    return token


def read_token(token_file: str) -> str:
    # Relative to REGISTRY_DIR (current), or absolute (entries from older versions).
    path = Path(token_file)
    if not path.is_absolute():
        path = REGISTRY_DIR / path
    return path.read_text(encoding="utf-8").strip()


def register(name: str, port: int, url: str, token_file: str, pid: int) -> None:
    data = _load_raw()
    data[name] = {
        "port": port,
        "url": url,
        "token_file": token_file,
        "pid": pid,
        "pid_ns": pid_namespace(),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    _save(data)


def unregister(name: str) -> None:
    data = _load_raw()
    if name in data:
        del data[name]
        _save(data)


def get(name: str) -> dict | None:
    return load().get(name)


def list_all() -> dict:
    return load()
