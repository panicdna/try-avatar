---
name: avatar-a2a-bridge
description: Expose a local avatar as a remote A2A (Agent2Agent, the open Google/Linux-Foundation protocol) server, or call one running in another Claude Code session, so two avatars talk directly over HTTP/JSON-RPC instead of through a shared coordinator session. Use when the user wants avatar-to-avatar / agent-to-agent / A2A / peer-to-peer communication between avatars, or asks to "serve" an avatar for another session to reach, or to "call" a peer avatar by name. Scope: same machine, different Claude Code sessions (see the design doc for why cross-machine is out of scope for now).
license: Apache-2.0
compatibility: Python 3.10+, third-party packages a2a-sdk[http-server] and uvicorn (scripts/requirements.txt). Binds 127.0.0.1 only. No corp-network dependency.
---

# avatar-a2a-bridge

Lets one avatar (a Claude Code session/subagent) act as an **A2A server** that
another Claude Code session can reach as an **A2A client**, directly over
HTTP — no coordinator session relaying between them. This is the real, open
[A2A (Agent2Agent) protocol](https://a2a-protocol.org/latest/specification/)
(Google → Linux Foundation, v1.0), not a project-specific stand-in, so a
correctly-configured peer speaking standard A2A (this skill's own server, or
someone else's) can talk to it too.

**Current scope**: same machine, different Claude Code sessions/processes,
each bound to `127.0.0.1`. Real cross-machine deployment (TLS, real domains,
firewalls) is an explicit next phase, not yet built — see
`docs/superpowers/specs/2026-09-12-avatar-a2a-bridge-design.md` for the full
design and the reasoning behind that scoping.

**Terminology**: A2A's own "Agent Card" (this skill's `/.well-known/agent-card.json`)
is unrelated to Agent Factory's "Avatar Card" (`agent-factory-api`'s
`POST /avatars/cards`) — same term, different systems. This skill only speaks
A2A; converting an Agent Factory Avatar Card into this skill's `skills-file`
JSON is a separate, manual step (see below), so it never needs Agent Factory
credentials itself.

## Setup

```bash
pip install -r "${CLAUDE_PLUGIN_ROOT}/skills/avatar-a2a-bridge/scripts/requirements.txt"
```

(or into a venv — the scripts have no other dependency on how Python was
installed).

## Serving an avatar

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/avatar-a2a-bridge/scripts/serve.py" \
  --name voc-avatar-operator \
  --description "VoC 처리 방식을 판단하고 지시하는 운영자" \
  --skills-file operator-skills.json
```

Run this in the session that *is* the avatar. It picks a free local port,
writes a bearer token to `~/.a2a-avatars/tokens/<name>.token` (chmod 600),
serves the A2A Agent Card + JSON-RPC endpoint, and registers itself (name →
port, url, token file, pid) in `~/.a2a-avatars/registry.json` so `call.py` in
another session can find it. It runs in the foreground — start it with
`run_in_background` (the harness's Bash tool option) so the session that
started it can keep doing other work; it deregisters cleanly on SIGINT/SIGTERM
(session/process end). A `SIGKILL` skips that cleanup, but the registry
prunes any entry whose pid is no longer alive the next time it's read, so a
stale entry never needs manual deletion — `call.py --peer <name>` on that
entry just reports the peer unreachable.

`--skills-file` is a JSON array: `[{"id","name","description","tags":[...]}, ...]`.
**To build one from an Agent Factory Avatar Card**: use the `agent-factory-api`
skill to `GET /avatars/cards/{id}` (and its roles/tasks), then hand-write the
resulting task titles/descriptions into this shape yourself — this skill
deliberately does not call the Agent Factory API on its own (keeps the A2A
transport layer and the Agent Factory catalog layer independent, and this
skill never needs `AGENT_FACTORY_API_KEY`). Without `--skills-file`, a single
skill is advertised using `--name`/`--description`.

**What actually answers an incoming message** is controlled by
`--exec-command`:

- Omitted (default): every message gets echoed back as `[echo] <message>` —
  use this first, to prove the two sessions can actually reach each other,
  before wiring anything real behind it.
- `--exec-command "<shell command>"`: that command runs **once per incoming
  message**, the message text on its stdin, its stdout (trimmed) becomes the
  A2A reply. If that command itself invokes Claude (e.g. `claude -p --agent
  voc-avatar-operator`), **every message a peer sends triggers a real, billed
  model call** — opt into this per avatar deliberately, it is not a safe
  default to leave running unattended.

## Calling a peer avatar

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/avatar-a2a-bridge/scripts/call.py" --list
python3 "${CLAUDE_PLUGIN_ROOT}/skills/avatar-a2a-bridge/scripts/call.py" \
  --peer voc-avatar-operator --message "..."
python3 "${CLAUDE_PLUGIN_ROOT}/skills/avatar-a2a-bridge/scripts/call.py" \
  --peer voc-avatar-operator --file handoff.md
```

Looks `--peer` up in the shared registry, resolves its Agent Card, sends the
message over `message/send`, polls `tasks/get` until a terminal state, prints
the reply artifact text to stdout. Exit code is 0 only on
`TASK_STATE_COMPLETED`.

**Passes the message through exactly as given — no summarizing, rewriting,
or added scope/hints.** This is the same rule CLAUDE.md already states for
relaying content between `voc-avatar-partner` subagents in one session,
extended to this skill's outbound A2A calls: the session invoking `call.py`
is a relay, not an editor. Use `--file` for a handoff file so its bytes go
out unedited, or `--message` with the caller's own text verbatim.

## Auth model

Same-machine processes under the same user, so the threat model is modest,
but the skill still follows the A2A spec's own recommendation (no static
secrets embedded in the Agent Card): the Agent Card itself
(`/.well-known/agent-card.json`) is served without auth (it's meant to be
discoverable), while the actual JSON-RPC endpoint requires
`Authorization: Bearer <token>` — the random per-avatar token `serve.py`
generates at startup. `call.py` reads that token from the registry entry's
`token_file`, which only the local user can read (`chmod 600`). On Windows
`chmod` doesn't restrict reads — the token is only as private as the
directory's ACL, so keep `$A2A_AVATARS_DIR` under your user profile unless you
deliberately share it.

## Registry

`~/.a2a-avatars/registry.json` + `~/.a2a-avatars/tokens/*.token` (override
the base directory with `$A2A_AVATARS_DIR`, e.g. to isolate a test run). Both
`serve.py`/`registry.py` create these with `0700`/`0600` permissions.
`call.py --list` is the quickest way to see who's currently reachable.

**WSL ↔ Windows on the same PC**: the two sides have different home
directories, so point both `$A2A_AVATARS_DIR`s at one shared directory
(`C:\x\reg` on Windows = `/mnt/c/x/reg` in WSL). Each entry records the pid
space it was registered from (`pid_ns`) and a `token_file` relative to the
registry directory, so either side can read the token; entries from the other
side are never pid-pruned (their pid means nothing here), and `call.py --list`
marks them `other-env:reachable|unreachable` instead of `local`. Whether
`127.0.0.1` reaches across depends on WSL2's networking mode: with
`networkingMode=mirrored` (+ `hostAddressLoopback=true`) in `.wslconfig`,
both directions work (verified both ways); with the default NAT mode, only
Windows → WSL works (localhost forwarding) and WSL → Windows usually doesn't.
On Windows, `python`/`python3` may
resolve to the Microsoft Store stub — run the scripts with `py`.

## Cross-machine (two separate PCs, e.g. over the internet)

The shared-file registry only works when both sessions share a filesystem, so
`--peer` is same-machine only. For a peer on a **different machine** the two
sides are wired by hand instead:

1. **Server PC** — put a TLS-terminating tunnel or a port-forward in front of
   the local port so the peer has a URL that reaches it, and advertise that URL
   (the A2A client POSTs to the interface URL *inside* the Card, not to the base
   URL it fetched the Card from — so the Card must carry a reachable URL):

   ```bash
   # e.g. a Cloudflare quick tunnel gives an https URL with no signup:
   cloudflared tunnel --url http://localhost:8710      # -> https://XXXX.trycloudflare.com
   python3 .../serve.py --name my-avatar --description "..." \
     --host 127.0.0.1 --port 8710 \
     --advertise-url https://XXXX.trycloudflare.com --print-token
   ```

   `--print-token` writes the bearer token to stderr; hand the public URL + that
   token to the caller out of band (the caller can't read this machine's token
   file). `--host 0.0.0.0` (instead of a tunnel) exposes the raw port for a
   plain LAN/port-forward setup.

2. **Client PC** — skip the registry, pass the URL and token directly:

   ```bash
   python3 .../call.py --url https://XXXX.trycloudflare.com \
     --token <token> --message "..."
   # or --token-file <path> to read the token from a file instead
   ```

Same auth model as local (Card public, JSON-RPC requires the Bearer token).
Use a tunnel/reverse-proxy that terminates TLS for anything crossing an
untrusted network — the bearer token is the only thing protecting the endpoint,
so it must not travel in clear text.

## Known limitations (see the design doc for the full list)

- Same-machine `--peer` discovery only (WSL ↔ Windows on one PC included).
  Cross-machine works but is wired by hand (above): no automatic discovery, and
  TLS is whatever the tunnel/proxy in front provides — this skill serves plain
  HTTP on its bound port.
- No streaming (`message/stream`/SSE) or push notifications — synchronous
  `message/send` + polling `tasks/get` only.
- `cancel` is not implemented.
- An Avatar Card that changes after `serve.py` started isn't picked up —
  restart `serve.py` to refresh the skills advertised in the Agent Card.
