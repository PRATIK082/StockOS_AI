"""Agent skill packs (P5-c, opt-in).

Flag: ``STOCKOS_AGENT_SKILLS`` — ``off`` (default), ``all``, or a comma
list of skill names. Skills are plain markdown files in
``app/services/agents/skills/*.md`` (first ``# Heading`` = title, rest =
prompt body) loaded as extra system-prompt blocks for the chat agent.
``STOCKOS_AGENT_SKILLS_DIR`` overrides the directory (used by tests).
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger("agent.skills")


@dataclass
class Skill:
    name: str
    title: str
    body: str
    chars: int

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("body", None)
        return d


def skills_dir() -> Path:
    override = os.environ.get("STOCKOS_AGENT_SKILLS_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "skills"


def skills_selection() -> str:
    return (os.environ.get("STOCKOS_AGENT_SKILLS") or "off").strip().lower()


def load_skills() -> dict[str, Skill]:
    """Load all *.md skill files. Broken files are skipped with a warning."""
    out: dict[str, Skill] = {}
    try:
        files = sorted(skills_dir().glob("*.md"))
    except OSError:
        return out
    for f in files:
        try:
            text = f.read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            logger.warning("skill file unreadable: %s", f.name)
            continue
        if not text:
            continue
        lines = text.splitlines()
        title = lines[0].lstrip("# ").strip() if lines[0].startswith("#") else f.stem
        body = "\n".join(lines[1:]).strip() or text
        out[f.stem.lower()] = Skill(name=f.stem.lower(), title=title, body=body, chars=len(body))
    return out


def resolve(names: list[str] | None) -> tuple[list[Skill], list[str]]:
    """Resolve requested names against loaded skills. Unknown -> skipped list."""
    if not names:
        return [], []
    available = load_skills()
    found, skipped = [], []
    for n in names:
        key = (n or "").strip().lower()
        if key in available:
            found.append(available[key])
        elif key:
            skipped.append(n)
    return found, skipped


def render(names: list[str] | None) -> str:
    """Render skill bodies as one system-prompt block (empty when none)."""
    found, _ = resolve(names)
    if not found:
        return ""
    parts = [f"### Skill: {s.title}\n{s.body}" for s in found]
    return "Active agent skills (apply these domain rules):\n" + "\n\n".join(parts)
