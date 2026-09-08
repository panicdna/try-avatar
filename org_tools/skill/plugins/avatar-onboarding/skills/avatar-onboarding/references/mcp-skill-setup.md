# MCP/Skill setup procedure

For every MCP server or Skill referenced by the selected Card/Role/Task -- as a structured
skill-component link *or* as a free-text mention in the Card/Role/Task prose -- resolve it
before offering install, using the decision procedure below. Use the **MCP/Skill setup
approval format** in `SKILL.md` before running any command or applying any credential.
Naming a requirement in the Card/Task text is a requirement *declaration*, not evidence that
it is installed -- never treat the two as the same thing.

## 1. Find every requirement

- **Structured**: fetch the Task's linked-skill summary via `agent-factory-api`. That summary
  does not itself return a component's `kind`/`type` -- for each linked component whose kind
  you don't already know, fetch that component's item detail separately to read it (`kind` /
  `type`, e.g. `mcp_server` vs `skill`; for `mcp_server` also read `mcp_server_fields` such as
  `endpoint_url`/`transport` if present). Confirm the exact endpoint/field names against
  the `agent-factory-api` skill's own reference docs or `/api/docs` before calling -- do
  not guess.
- **Free-text**: read the Card/Role/Task text for tool/MCP/Skill names the prose asks the
  avatar to use. These have no structured `kind` -- treat kind and connection info as unknown
  until the interview/search below establishes them.

## 2. Decision procedure per requirement

### (a) Structured component, kind = `mcp_server`

1. Read known fields (`endpoint_url`, `transport`) from the component detail, if present.
2. Check local presence with `claude mcp list` (name match; note whether the matched server
   is connected, failed, or paused) and `claude mcp get <name>` for detail when present.
3. If present: ask the user to choose reuse vs reinstall/reconfigure. Show only non-secret
   fields of the current config -- never display a stored secret value.
4. If absent, or the user chose reinstall: propose `claude mcp add <name> <endpoint_url> -t
   <transport> ...` via the approval format. Run the credential interview (section 3) first
   for any required `-e`/`--header`/OAuth value that's missing.

### (b) Free-text-only MCP mention, no structured metadata

1. Identify what the MCP actually is before doing anything -- ask the user, or infer from
   Card/Role/Task context. Do not guess a command/URL. If it can't be identified with
   confidence, mark the readiness-checklist item **unavailable** with that reason instead of
   fabricating a `claude mcp add` command.
2. Once identified: same as (a) steps 2-4, using `claude mcp add <name> <commandOrUrl> ...`.
3. If the mention turns out not to be an MCP server at all (e.g. it actually names a Skill or
   a plain tool), redirect to case (c)/(d).

### (c) Structured component, kind = `skill`

In this org's Claude Code deployment, any Skill that is itself an Agent Factory catalog item
self-installs the moment the `Skill` tool is invoked with its name -- this is the same
"well-known" auto-resolution that installed the `agent-factory-api` and `avatar-onboarding`
skills themselves during onboarding, with no separate install step. Since a Card/Role/Task's
linked skill components are by definition already Agent Factory catalog items, there is
**nothing to proactively install** for this case. Verify only:

1. The name matches exactly (case, hyphenation) what the Task/Role prose expects.
2. It resolves -- note that the assistant will invoke it once with `Skill(skill: <name>)` at
   first real use rather than during setup, unless the user wants to verify it now.

Do not run `claude plugin install` or `npx skills add` for this case -- that would be a
redundant, wrong install path for something the platform already resolves on its own.

### (d) Free-text-only Skill mention, not in Agent Factory's registry

Applies when a mention names a Skill that is not an Agent Factory catalog item -- e.g. an
external plugin-marketplace skill or a GitHub-hosted `skills add` package.

1. Confirm it is actually case (d) and not (c): search Agent Factory's own skill catalog via
   `agent-factory-api` (its catalog search/list endpoint -- check current field/endpoint names
   in that skill's reference docs) for the name before assuming it needs an external install.
2. If genuinely external, ask the user to identify the exact source: a plugin marketplace +
   plugin name (for `claude plugin install <plugin>[@marketplace]`) or a package identifier
   (for `npx skills add <package>`).
3. Propose the exact install command via the approval format, using the narrowest scope the
   tool supports (`claude plugin install` defaults to `user` scope -- only use that if a
   narrower scope isn't available, and say so).
4. After install, confirm it now resolves before treating the checklist item as answered.

## 3. Credential interview

When an MCP needs credentials/config to function:

- Prefer asking the user to run the `claude mcp add ... -e KEY=value ...` (or `--header`,
  `claude mcp login`) command themselves -- either by typing `!<command>` so the output lands
  in the transcript without the assistant ever seeing or relaying the secret, or by having
  already exported the value in their own shell before approving the proposed command. This
  chat has no masked-input primitive equivalent to a local CLI's `getpass()`, so self-entry is
  the default way to avoid putting a secret in the conversation transcript.
- Only fall back to the assistant running the command directly via Bash if the user explicitly
  chooses to paste the secret in chat anyway -- treat that as their informed choice, not the
  default path.
- Never write a secret value into the generated profile
  (`~/.agent-factory/avatars/<card-slug>/profile.md`), a Card/Role/Task payload, or the final
  response -- record only which keys were set and where (matches the Safety-boundary rule
  against writing to a user-global path without confirmation, and the "system of record" rule
  for domain data).
- Only add or update the specific missing keys for the target server; never touch unrelated
  existing MCP servers' entries or other stored config when writing (same idempotent-merge
  principle other skills in this workspace already use for shared config files).

## 4. Verify current CLI documentation

`claude mcp`, `claude plugin`, and `npx skills` flags and defaults can change across Claude
Code releases. Verify current `claude mcp add --help` / `claude plugin --help` output when a
flag, default scope, or transport option is uncertain; do not invent flags.
