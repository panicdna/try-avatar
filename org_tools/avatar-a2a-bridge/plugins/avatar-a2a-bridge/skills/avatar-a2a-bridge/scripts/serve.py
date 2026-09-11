#!/usr/bin/env python3
"""avatar-a2a-bridge: expose a local avatar as an A2A (Agent2Agent) server.

Usage:
  serve.py --name voc-avatar-operator --description "..." \\
      --skills-file skills.json
  serve.py --name my-avatar --description "a test avatar"
  serve.py --name my-avatar --description "..." \\
      --exec-command "claude -p --agent my-avatar"

skills.json format: [{"id": "...", "name": "...", "description": "...",
                       "tags": ["..."]}, ...]  -- convert an Agent Factory
Avatar Card's roles/tasks into this shape yourself (the agent-factory-api
skill fetches the Card; this script only speaks A2A, not the Agent Factory
API, on purpose -- see the design doc's "미해결 질문" section).

Without --exec-command, incoming messages are just echoed back -- useful to
prove the protocol round-trip before wiring a real avatar behind it. With
--exec-command, that command runs as a subprocess FOR EVERY INCOMING MESSAGE:
the message text is piped to its stdin, and its stdout (stripped) becomes the
A2A reply. If the command itself invokes Claude, every message a peer sends
triggers a real, billed model call -- opt into --exec-command per avatar,
don't treat it as a safe default.

Binds 127.0.0.1 only (same-machine, multi-Claude-Code-session prototype
scope; see docs/superpowers/specs/2026-09-12-avatar-a2a-bridge-design.md).
Registers itself in the local discovery registry (registry.py) under --name
so `call.py --peer <name>` on another session can find it, and deregisters on
SIGINT/SIGTERM. A SIGKILL leaves a stale registry entry; registry.py prunes
it automatically on the next read (it checks whether the recorded pid is
still alive), so `call.py` never manually cleans it up.
"""
import argparse
import asyncio
import json
import os
import shlex
import signal
import socket
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import registry  # noqa: E402

import uvicorn  # noqa: E402
from a2a.helpers import get_message_text, new_task_from_user_message, new_text_message, new_text_part  # noqa: E402
from a2a.server.agent_execution import AgentExecutor, RequestContext  # noqa: E402
from a2a.server.events import EventQueue  # noqa: E402
from a2a.server.request_handlers import DefaultRequestHandler  # noqa: E402
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes  # noqa: E402
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater  # noqa: E402
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.middleware import Middleware  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402

AGENT_CARD_PATH = "/.well-known/agent-card.json"


def bind_socket(port: int | None) -> socket.socket:
    """Bind (and start listening on) 127.0.0.1:`port`, or an OS-assigned free
    port if `port` is None. Returns the live socket -- callers must keep it
    open and hand it to uvicorn.Server.run(sockets=[...]) rather than closing it and
    passing a bare port number: in this environment, closing and immediately
    rebinding an ephemeral port loses the race to something else grabbing it
    (observed failing ~4 times out of 5 in testing) even though the same
    pattern is the textbook-safe way to do this on plain Linux."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port or 0))
    sock.listen(128)
    return sock


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Requires `Authorization: Bearer <token>` on every route except the
    public Agent Card -- matches the A2A spec's recommendation that Cards
    stay publicly discoverable while actual task execution is protected."""

    def __init__(self, app, token: str):
        super().__init__(app)
        self.token = token

    async def dispatch(self, request, call_next):
        if request.url.path == AGENT_CARD_PATH:
            return await call_next(request)
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


class BridgeExecutor(AgentExecutor):
    """Runs `exec_command` per incoming message if given, else echoes it back."""

    def __init__(self, exec_command: str | None, timeout: float):
        self.exec_command = exec_command
        self.timeout = timeout

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)
        await updater.start_work()
        text = get_message_text(context.message)
        try:
            reply = await self._run(text)
        except subprocess.TimeoutExpired:
            await updater.failed(message=new_text_message(f"exec-command timed out after {self.timeout}s"))
            return
        except Exception as exc:  # noqa: BLE001 - surface any executor failure to the caller, not a 500
            await updater.failed(message=new_text_message(f"exec-command failed: {exc}"))
            return
        await updater.add_artifact(parts=[new_text_part(text=reply)], name="reply")
        await updater.complete()

    async def _run(self, text: str) -> str:
        if not self.exec_command:
            return f"[echo] {text}"
        # POSIX shlex treats backslashes as escapes, which mangles C:\ paths on Windows.
        argv = shlex.split(self.exec_command, posix=os.name != "nt")
        if os.name == "nt":
            argv = [a[1:-1] if len(a) >= 2 and a[0] == a[-1] == '"' else a for a in argv]
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(text.encode()), timeout=self.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise subprocess.TimeoutExpired(self.exec_command, self.timeout)
        if proc.returncode != 0:
            raise RuntimeError(f"exit {proc.returncode}: {err.decode(errors='replace')[:2000]}")
        return out.decode(errors="replace").strip()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("cancel is not supported by avatar-a2a-bridge yet")


def load_skills(args: argparse.Namespace) -> list[AgentSkill]:
    if args.skills_file:
        raw = json.loads(Path(args.skills_file).read_text())
        return [
            AgentSkill(id=s["id"], name=s["name"], description=s.get("description", ""), tags=s.get("tags", []))
            for s in raw
        ]
    return [AgentSkill(id=args.name, name=args.name, description=args.description, tags=["avatar-a2a-bridge"])]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True, help="discovery name; other sessions call.py --peer this")
    p.add_argument("--description", default="", help="A2A Agent Card description")
    p.add_argument("--skills-file", help="JSON file: [{id,name,description,tags}, ...]")
    p.add_argument("--exec-command", help="shell command run per message; stdin=message text, stdout=reply")
    p.add_argument("--timeout", type=float, default=60.0, help="seconds to wait for --exec-command (default 60)")
    p.add_argument("--port", type=int, help="bind this port instead of an OS-assigned free one")
    args = p.parse_args()

    existing = registry.get(args.name)
    if existing and registry.is_local(existing):
        sys.exit(
            f"'{args.name}' is already registered and its serving process is alive. "
            f"Stop it first, or pick a different --name."
        )
    if existing:
        sys.exit(
            f"'{args.name}' is already registered from another environment "
            f"(pid_ns={existing.get('pid_ns')}), whose process can't be checked from here. "
            f"Stop it there (if it's already dead, `call.py --list` there prunes it), "
            f"or pick a different --name."
        )

    sock = bind_socket(args.port)
    port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    token = registry.new_token(args.name)
    token_file = registry.token_ref(args.name)

    card = AgentCard(
        name=args.name,
        description=args.description,
        version="0.1.0",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[AgentInterface(url=url, protocol_binding="JSONRPC", protocol_version="1.0")],
        skills=load_skills(args),
    )
    handler = DefaultRequestHandler(
        agent_executor=BridgeExecutor(args.exec_command, args.timeout),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    routes = create_agent_card_routes(card, card_url=AGENT_CARD_PATH) + create_jsonrpc_routes(handler, "/")
    app = Starlette(routes=routes, middleware=[Middleware(BearerAuthMiddleware, token=token)])

    registry.register(args.name, port, url, token_file, os.getpid())

    def _cleanup(signum, frame):  # noqa: ARG001
        registry.unregister(args.name)
        sys.exit(0)

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    print(f"[avatar-a2a-bridge] serving '{args.name}' at {url}{AGENT_CARD_PATH}", file=sys.stderr)
    print(f"[avatar-a2a-bridge] registered in {registry.REGISTRY_FILE}", file=sys.stderr)
    try:
        # Hand uvicorn the live socket itself, not fd=sock.fileno(): uvicorn
        # rebuilds an fd as AF_UNIX, which doesn't exist on Windows.
        uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[sock])
    finally:
        registry.unregister(args.name)


if __name__ == "__main__":
    main()
