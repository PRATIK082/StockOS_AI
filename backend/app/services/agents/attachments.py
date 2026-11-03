"""User attachments for the chat agent (P5-c).

Flag: ``STOCKOS_AGENT_ATTACHMENTS`` — ``on`` (default) or ``off``.
Storage is local only: ``backend/data/attachments/<user_id>/`` (``backend/data/``
is gitignored). No DB migration — a per-user ``index.json`` sidecar tracks
metadata.

Text-like files (.txt/.md/.csv/.json) get their text extracted (capped);
images/PDFs are stored with metadata only and reported honestly as such.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger("agent.attachments")

MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB per file
MAX_FILES_PER_USER = 20
TEXT_CHARS_CAP = 20_000  # extraction cap per file
CHAT_CONTEXT_CAP = 12_000  # total chars forwarded into chat context

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json", ".log"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
ALLOWED_SUFFIXES = TEXT_SUFFIXES | IMAGE_SUFFIXES | {".pdf"}

_storage_override: Path | None = None


class AttachmentsDisabledError(RuntimeError):
    pass


def attachments_enabled() -> bool:
    return (os.environ.get("STOCKOS_AGENT_ATTACHMENTS") or "on").strip().lower() != "off"


def _base_dir() -> Path:
    if _storage_override is not None:
        return _storage_override
    return Path(__file__).resolve().parents[3] / "data" / "attachments"


def _user_dir(user_id: str) -> Path:
    # user_id comes from our own auth layer; still, keep it filename-safe.
    safe = re.sub(r"[^A-Za-z0-9_=@.+-]", "_", str(user_id))[:64] or "anon"
    d = _base_dir() / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path(user_id: str) -> Path:
    return _user_dir(user_id) / "index.json"


def _read_index(user_id: str) -> dict:
    p = _index_path(user_id)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("attachment index unreadable, starting fresh")
        return {}


def _write_index(user_id: str, index: dict) -> None:
    _index_path(user_id).write_text(json.dumps(index, indent=1), encoding="utf-8")


@dataclass
class Attachment:
    id: str
    filename: str
    kind: str  # "text" | "image" | "pdf" | "other"
    size: int
    text_chars: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _classify(suffix: str) -> str:
    if suffix in TEXT_SUFFIXES:
        return "text"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix == ".pdf":
        return "pdf"
    return "other"


def save_upload(user_id: str, filename: str, data: bytes) -> Attachment:
    """Persist an upload; raises AttachmentsDisabledError / ValueError."""
    if not attachments_enabled():
        raise AttachmentsDisabledError(
            "Attachments are disabled. Set STOCKOS_AGENT_ATTACHMENTS=on to enable."
        )
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"File exceeds {MAX_FILE_BYTES // (1024 * 1024)} MB limit.")
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f"Unsupported file type '{suffix}'. Allowed: {sorted(ALLOWED_SUFFIXES)}")

    index = _read_index(user_id)
    if len(index) >= MAX_FILES_PER_USER:
        raise ValueError(f"Attachment limit reached ({MAX_FILES_PER_USER} files). Delete one first.")

    safe_name = re.sub(r"[^A-Za-z0-9_.\-]", "_", Path(filename).name)[-80:] or "file"
    att_id = uuid.uuid4().hex[:16]
    stored = f"{att_id}_{safe_name}"
    dest = _user_dir(user_id) / stored
    # Path-traversal guard (belt and braces: name is sanitized, verify anyway).
    if dest.resolve().parent != _user_dir(user_id).resolve():
        raise ValueError("Invalid filename.")
    dest.write_bytes(data)

    kind = _classify(suffix)
    text = ""
    if kind == "text":
        try:
            text = data.decode("utf-8", errors="replace")[:TEXT_CHARS_CAP]
        except Exception:  # noqa: BLE001 - extraction is best-effort
            text = ""
    if text:
        (dest.with_suffix(dest.suffix + ".extracted.txt")).write_text(text, encoding="utf-8")

    att = Attachment(id=att_id, filename=Path(filename).name[:120], kind=kind,
                     size=len(data), text_chars=len(text))
    index[att_id] = {"stored": stored, **att.to_dict()}
    _write_index(user_id, index)
    return att


def list_attachments(user_id: str) -> list[dict]:
    return [Attachment(**{k: v for k, v in meta.items() if k != "stored"}).to_dict()
            for meta in _read_index(user_id).values()]


def load_texts(user_id: str, att_ids: list[str]) -> tuple[list[dict], list[str]]:
    """Return ([{id, filename, text}], [skipped_ids]). Missing IDs are skipped."""
    index = _read_index(user_id)
    found, skipped = [], []
    for aid in att_ids:
        meta = index.get(aid)
        if not meta:
            skipped.append(aid)
            continue
        if meta.get("kind") != "text" or not meta.get("text_chars"):
            skipped.append(aid)
            continue
        sidecar = _user_dir(user_id) / (meta["stored"] + ".extracted.txt")
        try:
            found.append({"id": aid, "filename": meta["filename"],
                          "text": sidecar.read_text(encoding="utf-8")})
        except OSError:
            skipped.append(aid)
    return found, skipped


def delete_attachment(user_id: str, att_id: str) -> bool:
    index = _read_index(user_id)
    meta = index.pop(att_id, None)
    if not meta:
        return False
    for name in (meta["stored"], meta["stored"] + ".extracted.txt"):
        try:
            (_user_dir(user_id) / name).unlink(missing_ok=True)
        except OSError:  # noqa: TRY203 - best-effort cleanup
            pass
    _write_index(user_id, index)
    return True
