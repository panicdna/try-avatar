#!/usr/bin/env python3
"""Self-check for avatar-a2a-bridge (serve.py/call.py/registry.py) -- run:
  pip install -r requirements.txt   # a2a-sdk[http-server], uvicorn
  python3 test_bridge.py

Framework-free asserts, mirroring bedrock-cost-report's test_driver.py style.
This only exercises the A2A transport layer itself -- every server started
here is a disposable --skills-file/echo/stub fixture in an isolated registry
dir, NEVER the real voc-avatar-partner resolver and NEVER the real Agent
Factory Avatar Card (this skill doesn't call the Agent Factory API at all,
by design -- see SKILL.md). Nothing here touches GitHub or sends anything.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    import a2a  # noqa: F401
except ImportError:
    sys.exit(
        "a2a-sdk is not installed in this Python. Run:\n"
        "  pip install -r requirements.txt\n"
        "(or point this interpreter at a venv that has it) and re-run this test."
    )

HERE = Path(__file__).parent
PY = sys.executable

TMP = Path(tempfile.mkdtemp(prefix="avatar-a2a-bridge-test-"))
os.environ["A2A_AVATARS_DIR"] = str(TMP / "registry")  # isolate from ~/.a2a-avatars/

sys.path.insert(0, str(HERE))
import registry  # noqa: E402  -- import AFTER setting A2A_AVATARS_DIR, it reads env at import time
import serve  # noqa: E402  -- for advertised_url() unit coverage

REGISTRY_FILE = TMP / "registry" / "registry.json"


def run_call(*args, timeout=15, env=None):
    return subprocess.run(
        [PY, str(HERE / "call.py"), *args], capture_output=True, text=True, timeout=timeout,
        env={**os.environ, **(env or {})},
    )


def start_serve(name, *extra_args):
    proc = subprocess.Popen(
        [PY, str(HERE / "serve.py"), "--name", name, "--description", "test avatar", *extra_args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    for _ in range(50):  # up to ~5s for uvicorn to come up and register
        if REGISTRY_FILE.exists():
            data = json.loads(REGISTRY_FILE.read_text())
            if name in data:
                return proc, data[name]
        time.sleep(0.1)
    proc.kill()
    out = proc.stdout.read() if proc.stdout else ""
    raise AssertionError(f"'{name}' never registered within 5s\n{out}")


def stop_serve(proc, name):
    proc.terminate()
    proc.wait(timeout=5)
    if os.name == "nt":
        # terminate() is TerminateProcess on Windows: no SIGTERM handler runs, so
        # the entry goes away through the dead-pid prune on the next read instead.
        assert registry.get(name) is None, f"'{name}' still returned after its process died"
        return
    data = json.loads(REGISTRY_FILE.read_text()) if REGISTRY_FILE.exists() else {}
    assert name not in data, f"'{name}' still in registry after SIGTERM: {data}"


def main() -> None:
    # 1. registry.py, unit-level: token round trip + dead-pid entries are pruned
    tok = registry.new_token("unit-test-avatar")
    token_file = str(registry.TOKENS_DIR / "unit-test-avatar.token")
    assert registry.read_token(token_file) == tok
    registry.register("unit-test-avatar", 1234, "http://127.0.0.1:1234", token_file, pid=2**31 - 1)
    assert registry.get("unit-test-avatar") is None, "an entry whose pid is dead must be pruned, not returned"
    assert registry.read_token(registry.token_ref("unit-test-avatar")) == tok, "relative token_file must resolve"
    print("PASS  registry: token round trip + dead-pid prune")

    # 1b. an entry from another pid space (WSL <-> Windows sharing one
    # A2A_AVATARS_DIR) is kept even with a "dead" pid: it can't be checked here
    registry.register("foreign-avatar", 1, "http://127.0.0.1:1", registry.token_ref("foreign-avatar"), pid=2**31 - 1)
    data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    data["foreign-avatar"]["pid_ns"] = "some-other-environment"
    REGISTRY_FILE.write_text(json.dumps(data), encoding="utf-8")
    foreign = registry.get("foreign-avatar")
    assert foreign is not None, "an other-environment entry must not be pid-pruned"
    assert not registry.is_local(foreign)
    assert not registry.probe("foreign-avatar", foreign), "nothing serves an Agent Card on port 1"
    registry.unregister("foreign-avatar")
    print("PASS  registry: other-environment entries kept, not pid-pruned")

    # 2. echo mode: the default executor, end to end over real HTTP/JSON-RPC
    proc, _entry = start_serve("echo-avatar")
    try:
        r = run_call("--peer", "echo-avatar", "--message", "hello test")
        assert r.returncode == 0, r.stdout + r.stderr
        assert r.stdout.strip() == "[echo] hello test", r.stdout
    finally:
        stop_serve(proc, "echo-avatar")
    print("PASS  echo mode: call.py <-> serve.py round trip")

    # 3. --skills-file is reflected verbatim in the served Agent Card
    skills_file = TMP / "skills.json"
    skills_file.write_text(json.dumps([{"id": "s1", "name": "Skill One", "description": "d1", "tags": ["t"]}]))
    proc, entry = start_serve("skills-avatar", "--skills-file", str(skills_file))
    try:
        with urllib.request.urlopen(entry["url"] + "/.well-known/agent-card.json", timeout=5) as resp:
            card = json.loads(resp.read())
        assert [s["id"] for s in card["skills"]] == ["s1"], card["skills"]
    finally:
        stop_serve(proc, "skills-avatar")
    print("PASS  --skills-file: reflected in the served Agent Card")

    # 4. --exec-command routes through a REAL subprocess, not the built-in echo --
    # a stub stand-in, never the real resolver/GitHub-touching agent.
    stub = TMP / "stub_reverse.py"
    stub.write_text("import sys\nsys.stdout.write(sys.stdin.read().strip()[::-1])\n")
    proc, _entry = start_serve("exec-avatar", "--exec-command", f"{PY} {stub}")
    try:
        r = run_call("--peer", "exec-avatar", "--message", "hello")
        assert r.returncode == 0, r.stdout + r.stderr
        assert r.stdout.strip() == "olleh", r.stdout  # reversed input proves it's a real subprocess
    finally:
        stop_serve(proc, "exec-avatar")
    print("PASS  --exec-command: routes through a real subprocess (not the echo path)")

    # 5. bearer auth: Agent Card is public, the JSON-RPC endpoint requires the token
    proc, entry = start_serve("auth-avatar")
    try:
        req = urllib.request.Request(
            entry["url"] + "/", data=b"{}", headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("POST without a bearer token should have been rejected with 401")
        except urllib.error.HTTPError as e:
            assert e.code == 401, e.code
        with urllib.request.urlopen(entry["url"] + "/.well-known/agent-card.json", timeout=5) as resp:
            assert resp.status == 200, "Agent Card GET should stay public"
    finally:
        stop_serve(proc, "auth-avatar")
    print("PASS  auth: Agent Card public, JSON-RPC endpoint requires a valid Bearer token")

    # 6a. advertised_url(): the cross-machine URL logic, unit-level (no server) --
    # --advertise-url (a tunnel/port-forward public URL) wins; a concrete --host is
    # used as-is; a loopback/wildcard bind falls back to loopback.
    assert serve.advertised_url("127.0.0.1", 5000) == "http://127.0.0.1:5000"
    assert serve.advertised_url("0.0.0.0", 5000) == "http://127.0.0.1:5000"
    assert serve.advertised_url("10.0.0.9", 5000) == "http://10.0.0.9:5000"
    assert serve.advertised_url("0.0.0.0", 5000, "https://peer.example/") == "https://peer.example"
    print("PASS  advertised_url: --advertise-url / concrete host / loopback fallback")

    # 6b. cross-machine call path: call.py --url/--token reaches a peer with NO
    # registry entry (simulates a peer on another machine). The server is local
    # here, but the caller is pointed at a separate empty A2A_AVATARS_DIR, so a
    # registry lookup can't be what makes the call succeed.
    proc, entry = start_serve("xmachine-avatar")
    try:
        token = registry.read_token(registry.token_ref("xmachine-avatar"))
        empty_reg = {"A2A_AVATARS_DIR": str(TMP / "caller-registry")}
        r = run_call("--url", entry["url"], "--token", token, "--message", "ping", env=empty_reg)
        assert r.returncode == 0, r.stdout + r.stderr
        assert r.stdout.strip() == "[echo] ping", r.stdout
        bad = run_call("--url", entry["url"], "--token", "nope", "--message", "ping", env=empty_reg)
        assert bad.returncode != 0 and "401" in (bad.stdout + bad.stderr), (bad.stdout, bad.stderr)
    finally:
        stop_serve(proc, "xmachine-avatar")
    print("PASS  cross-machine: call.py --url/--token reaches a peer with no registry entry")

    print("\nALL PASS")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
