#!/usr/bin/env python3
"""avatar-a2a-bridge: call a locally-registered peer avatar over A2A.

Usage:
  call.py --list
  call.py --peer voc-avatar-operator --message "..."
  call.py --peer voc-avatar-operator --file handoff.md
  call.py --peer voc-avatar-operator --stdin < handoff.md

Looks the peer up in the local discovery registry (registry.py), resolves
its A2A Agent Card, sends the message over JSON-RPC (`message/send`) using
the peer's bearer token, then polls `tasks/get` until the task reaches a
terminal state. The reply artifact text goes to stdout; the exit code is 0
only on TASK_STATE_COMPLETED.

Passes the message through exactly as given -- this script does not
summarize, rewrite, or add scope/hints to it (see the coordinator-purity
rule in CLAUDE.md, which this extends to outbound A2A calls). If you are
relaying a handoff file, use --file so the bytes on disk go out unedited.
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import registry  # noqa: E402

import httpx  # noqa: E402
from a2a.client import A2AClientError, ClientConfig, create_client  # noqa: E402
from a2a.helpers import get_artifact_text, get_message_text, new_text_message  # noqa: E402
from a2a.types import GetTaskRequest, Role, SendMessageRequest, TaskState  # noqa: E402

TERMINAL_STATES = {
    TaskState.TASK_STATE_COMPLETED,
    TaskState.TASK_STATE_FAILED,
    TaskState.TASK_STATE_CANCELED,
    TaskState.TASK_STATE_REJECTED,
    TaskState.TASK_STATE_INPUT_REQUIRED,
    TaskState.TASK_STATE_AUTH_REQUIRED,
}


def read_message(args: argparse.Namespace) -> str:
    if args.file:
        return Path(args.file).read_text()
    if args.stdin:
        return sys.stdin.read()
    if args.message is not None:
        return args.message
    sys.exit("one of --message / --file / --stdin is required (see --list to check what's reachable)")


async def call(peer: str, text: str, timeout: float, poll_interval: float) -> int:
    entry = registry.get(peer)
    if entry is None:
        sys.exit(
            f"'{peer}' is not in the local registry ({registry.REGISTRY_FILE}) "
            f"or its serving process is no longer alive. Is `serve.py --name {peer}` "
            f"running in that other session? (`call.py --list` shows what's registered now.)"
        )
    token = registry.read_token(entry["token_file"])
    httpx_client = httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=timeout)

    try:
        client = await create_client(
            entry["url"], client_config=ClientConfig(streaming=False, polling=True, httpx_client=httpx_client)
        )
    except Exception as exc:  # noqa: BLE001 - report unreachable peer plainly
        hint = "" if registry.is_local(entry) else (
            " (registered from another environment: under WSL2's default NAT networking, "
            "WSL -> Windows localhost usually doesn't work; networkingMode=mirrored with "
            "hostAddressLoopback=true in .wslconfig makes both directions work)"
        )
        sys.exit(f"could not reach '{peer}' at {entry['url']}: {exc}{hint}")

    try:
        req = SendMessageRequest(message=new_text_message(text=text, role=Role.ROLE_USER))
        task_id = None
        async for resp in client.send_message(req):
            if resp.WhichOneof("payload") == "task":
                task_id = resp.task.id
        if task_id is None:
            sys.exit(f"'{peer}' accepted the call but returned no task")

        elapsed = 0.0
        final_task = None
        while elapsed < timeout:
            task = await client.get_task(GetTaskRequest(id=task_id))
            if task.status.state in TERMINAL_STATES:
                final_task = task
                break
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        if final_task is None:
            sys.exit(f"'{peer}' did not reach a terminal state within {timeout}s (task {task_id})")

        if final_task.status.state != TaskState.TASK_STATE_COMPLETED:
            state_name = TaskState.Name(final_task.status.state)
            detail = get_message_text(final_task.status.message) if final_task.status.HasField("message") else ""
            print(f"[{state_name}] {detail}", file=sys.stderr)
            return 1

        for art in final_task.artifacts:
            print(get_artifact_text(art))
        return 0
    except A2AClientError as exc:
        sys.exit(f"'{peer}' rejected the call: {exc}")
    finally:
        await client.close()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--peer", help="registered avatar name to call")
    p.add_argument("--message", help="message text, sent verbatim")
    p.add_argument("--file", help="read message text from this file, sent verbatim")
    p.add_argument("--stdin", action="store_true", help="read message text from stdin, sent verbatim")
    p.add_argument("--timeout", type=float, default=60.0, help="seconds to wait for a terminal task state")
    p.add_argument("--poll-interval", type=float, default=0.3, help="seconds between tasks/get polls")
    p.add_argument("--list", action="store_true", help="list currently registered avatars and exit")
    args = p.parse_args()

    if args.list:
        data = registry.list_all()
        if not data:
            print("(no avatars currently registered)")
            return
        for name, e in data.items():
            env = "local" if registry.is_local(e) else (
                f"other-env:{'reachable' if registry.probe(name, e) else 'unreachable'}"
            )
            print(f"{name}\t{e['url']}\tpid={e['pid']}\tstarted={e['started_at']}\t{env}")
        return

    if not args.peer:
        sys.exit("--peer is required (or use --list)")

    text = read_message(args)
    sys.exit(asyncio.run(call(args.peer, text, args.timeout, args.poll_interval)))


if __name__ == "__main__":
    main()
