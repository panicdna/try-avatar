#!/usr/bin/env python3
"""Single source of truth for platform subagent install-target paths.

install_avatar.py, backup_avatar.py, and restore_avatar.py each need to know where a
role's rendered subagent file lives for every platform. Keep that list here so the
three stay in sync instead of drifting independently when a platform target changes.
"""

from __future__ import annotations

# (platform, path template relative to its install root; "{name}" is "<card-slug>-<role-slug>")
INSTALL_TARGET_TEMPLATES: tuple[tuple[str, str], ...] = (
    ("claude", ".claude/agents/agent-factory/{name}.md"),
    ("opencode", ".config/opencode/agents/agent-factory/{name}.md"),
    ("codex", ".codex/agents/{name}.toml"),
)

# Directory prefix before "{name}" in each template above, e.g. ".claude/agents/agent-factory/" --
# lets a caller recognize a relative path as "under one of these install targets" (see
# restore_avatar.py's restore_local) without re-parsing INSTALL_TARGET_TEMPLATES itself.
INSTALL_TARGET_PREFIXES: tuple[str, ...] = tuple(template.split("{name}")[0] for _, template in INSTALL_TARGET_TEMPLATES)
