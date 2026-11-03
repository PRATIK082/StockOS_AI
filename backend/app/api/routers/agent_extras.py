"""P5-c agent-extras routes: voice STT, attachments, web search, skills.

Every capability is behind its own flag (see service modules); disabled or
missing-dependency backends return 501 with an actionable message, never a
traceback.
"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from app.api.deps import CurrentUser
from app.services.agents import attachments as attachment_store
from app.services.agents import skills as skill_packs
from app.services.agents import websearch
from app.services.voice import stt

router = APIRouter(tags=["ai-extras"])


# ------------------------------------------------------------------ voice STT
@router.post("/voice/transcribe")
async def voice_transcribe(file: UploadFile = File(...), user: CurrentUser = None) -> dict:
    data = await file.read()
    try:
        result = stt.transcribe_bytes(data, "." + (file.filename or "").rsplit(".", 1)[-1].lower()
                                      if "." in (file.filename or "") else "")
    except stt.STTUnavailableError as exc:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return {"text": result.text, "language": result.language,
            "duration_s": result.duration_s, "model": result.model}


# --------------------------------------------------------------- attachments
@router.post("/agent/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(file: UploadFile = File(...), user: CurrentUser = None) -> dict:
    data = await file.read()
    try:
        att = attachment_store.save_upload(str(user.id), file.filename or "file", data)
    except attachment_store.AttachmentsDisabledError as exc:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    out = att.to_dict()
    if att.kind == "text":
        found, _ = attachment_store.load_texts(str(user.id), [att.id])
        out["text_preview"] = (found[0]["text"][:500] if found else "")
    else:
        out["text_preview"] = ""
        out["note"] = "Only text files (.txt/.md/.csv/.json) are readable by the agent; this file is stored only."
    return out


@router.get("/agent/attachments")
async def list_my_attachments(user: CurrentUser = None) -> dict:
    return {"attachments": attachment_store.list_attachments(str(user.id))}


@router.delete("/agent/attachments/{att_id}")
async def delete_my_attachment(att_id: str, user: CurrentUser = None) -> dict:
    if not attachment_store.delete_attachment(str(user.id), att_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found.")
    return {"deleted": att_id}


# --------------------------------------------------------------- web search
@router.get("/agent/websearch")
async def agent_websearch(q: str = Query(min_length=1, max_length=300), user: CurrentUser = None) -> dict:
    try:
        return websearch.search(q)
    except websearch.WebSearchDisabledError as exc:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


# ------------------------------------------------------------------- skills
@router.get("/agent/skills")
async def agent_skills(user: CurrentUser = None) -> dict:
    return {
        "selection": skill_packs.skills_selection(),
        "skills": [s.to_dict() for s in skill_packs.load_skills().values()],
    }
