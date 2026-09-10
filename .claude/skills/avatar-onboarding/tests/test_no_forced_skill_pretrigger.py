from __future__ import annotations

from pathlib import Path

_SKILL_DIR = Path(__file__).parents[1]
_PLUGIN_DIR = Path(__file__).parents[3]

_SKILL_MD = _SKILL_DIR / "SKILL.md"
_MCP_SKILL_SETUP_MD = _SKILL_DIR / "references" / "mcp-skill-setup.md"
_README_MD = _PLUGIN_DIR / "README.md"

# This exact anti-pattern (forcing Skill(name) on every closure skill during onboarding, to
# pre-install it) has been rejected once (issue #66), reintroduced once through a stale
# squash-merge (main commit 24e6987), and reverted again (PR #69). None of those three round
# trips involved a code change -- only doc prose and ordinary git operations -- so nothing
# else in this suite would have caught the second reintroduction. These markers are narrow,
# single-line fragments of the known-bad wording, chosen so a differently-phrased future
# instruction to the same effect would not accidentally satisfy them.
_BAD_SKILL_MD_FRAGMENT = (
    "closure (step 9) -- this triggers each catalog skill's lazy self-install inside"
)
_BAD_MCP_SKILL_SETUP_FRAGMENT = (
    "for every closure skill during the install session itself -- otherwise the"
)
_BAD_README_FRAGMENT = "closure의 각 skill을 `Skill(name)`으로 이미 한 번씩"


def test_skill_md_does_not_force_pretrigger_on_closure() -> None:
    text = _SKILL_MD.read_text(encoding="utf-8")
    assert _BAD_SKILL_MD_FRAGMENT not in text
    assert "Do **not** call `Skill(name)` on the Role's closure (step 9)" in text


def test_mcp_skill_setup_does_not_force_pretrigger_on_closure() -> None:
    text = _MCP_SKILL_SETUP_MD.read_text(encoding="utf-8")
    assert _BAD_MCP_SKILL_SETUP_FRAGMENT not in text
    assert "call `Skill(name)` on every closure skill (step 9) from the onboarding session either, to" in text


def test_readme_does_not_force_pretrigger_on_closure() -> None:
    text = _README_MD.read_text(encoding="utf-8")
    assert _BAD_README_FRAGMENT not in text
    assert "정상이다" in text
