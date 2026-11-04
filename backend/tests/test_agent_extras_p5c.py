"""Tests for P5-c: voice STT, attachments, web search, skills (all faked, no network)."""

from __future__ import annotations

import sys
import types

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    import asyncio
    from app.main import app
    from app.db.base import Base
    from app.db.session import engine

    async def _init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth_headers(client):
    r = client.post(
        "/api/auth/register",
        json={"email": "agentextras@test.dev", "username": "agentextrasuser", "password": "secret123"},
    )
    if r.status_code == 201:
        token = r.json()["access_token"]
    elif r.status_code == 409:
        login = client.post("/api/auth/login", json={"identifier": "agentextrasuser", "password": "secret123"})
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
    else:
        raise AssertionError(f"Unexpected registration status: {r.status_code} {r.text}")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def user_id(client, auth_headers):
    r = client.get("/api/auth/me", headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture()
def tmp_store(monkeypatch, tmp_path):
    from app.services.agents import attachments

    monkeypatch.setattr(attachments, "_storage_override", tmp_path / "att")
    monkeypatch.setenv("STOCKOS_AGENT_ATTACHMENTS", "on")
    return tmp_path


def _fake_faster_whisper(monkeypatch):
    from app.services.voice import stt

    class _Seg:
        text = "hello market"

    class _Info:
        language = "en"
        duration = 1.5

    class _Model:
        def __init__(self, *a, **k):
            pass

        def transcribe(self, path, beam_size=5):
            return ([_Seg()], _Info())

    mod = types.ModuleType("faster_whisper")
    mod.WhisperModel = _Model
    monkeypatch.setitem(sys.modules, "faster_whisper", mod)
    monkeypatch.setenv("STOCKOS_VOICE_STT", "faster-whisper")
    return stt


def _capture_chat(monkeypatch):
    from app.services.llm.gateway import gateway

    seen: list = []

    async def fake_chat(self, messages, **kw):
        seen.extend(messages)
        return "canned answer"

    monkeypatch.setattr(gateway, "chat", fake_chat.__get__(gateway, type(gateway)))
    return seen


# ------------------------------------------------------------------ voice
def test_voice_disabled_by_default(client, auth_headers):
    r = client.post("/api/voice/transcribe", files={"file": ("t.wav", b"RIFFxx", "audio/wav")},
                    headers=auth_headers)
    assert r.status_code == 501, r.text
    assert "STOCKOS_VOICE_STT" in r.json()["detail"]


def test_voice_transcribes_with_fake_backend(client, auth_headers, monkeypatch):
    _fake_faster_whisper(monkeypatch)
    r = client.post("/api/voice/transcribe", files={"file": ("t.wav", b"RIFFxx", "audio/wav")},
                    headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text"] == "hello market"
    assert body["language"] == "en"
    assert body["duration_s"] == 1.5


def test_voice_missing_dep_is_501_with_hint(client, auth_headers, monkeypatch):
    monkeypatch.setenv("STOCKOS_VOICE_STT", "faster-whisper")
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    # Force re-import failure: drop any cached attribute is unnecessary since
    # _load_model does a fresh `from faster_whisper import ...` each call.
    r = client.post("/api/voice/transcribe", files={"file": ("t.wav", b"RIFFxx", "audio/wav")},
                    headers=auth_headers)
    assert r.status_code == 501, r.text
    assert "faster-whisper" in r.json()["detail"]


def test_voice_rejects_bad_type(client, auth_headers, monkeypatch):
    _fake_faster_whisper(monkeypatch)
    r = client.post("/api/voice/transcribe", files={"file": ("t.exe", b"MZ", "application/exe")},
                    headers=auth_headers)
    assert r.status_code == 422, r.text


# ------------------------------------------------------------ attachments
def test_attachment_upload_list_delete(client, auth_headers, tmp_store):
    up = client.post("/api/agent/attachments", files={"file": ("notes.txt", b"reliance results beat estimates", "text/plain")},
                     headers=auth_headers)
    assert up.status_code == 201, up.text
    body = up.json()
    assert body["kind"] == "text" and body["text_chars"] > 0
    assert "reliance" in body["text_preview"]

    listed = client.get("/api/agent/attachments", headers=auth_headers)
    assert listed.status_code == 200
    assert any(a["id"] == body["id"] for a in listed.json()["attachments"])

    img = client.post("/api/agent/attachments", files={"file": ("c.png", b"\x89PNGxx", "image/png")},
                      headers=auth_headers)
    assert img.status_code == 201, img.text
    assert img.json()["kind"] == "image"
    assert "note" in img.json()  # honest: images are stored, not read

    bad = client.post("/api/agent/attachments", files={"file": ("x.exe", b"MZ", "application/exe")},
                      headers=auth_headers)
    assert bad.status_code == 422, bad.text

    rm = client.delete(f"/api/agent/attachments/{body['id']}", headers=auth_headers)
    assert rm.status_code == 200, rm.text
    assert client.delete("/api/agent/attachments/nope", headers=auth_headers).status_code == 404


def test_attachment_disabled_flag(client, auth_headers, tmp_store, monkeypatch):
    monkeypatch.setenv("STOCKOS_AGENT_ATTACHMENTS", "off")
    r = client.post("/api/agent/attachments", files={"file": ("n.txt", b"hi", "text/plain")},
                    headers=auth_headers)
    assert r.status_code == 501, r.text


def test_chat_uses_attachment_text(client, auth_headers, tmp_store, monkeypatch):
    up = client.post("/api/agent/attachments", files={"file": ("memo.txt", b"quux quarter guidance raised", "text/plain")},
                     headers=auth_headers)
    aid = up.json()["id"]
    seen = _capture_chat(monkeypatch)
    r = client.post("/api/chat", json={"message": "summarize my file please", "attachment_ids": [aid, "missing"]},
                    headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(s == f"attachment:{aid}" for s in body["sources"])
    assert any("quux quarter" in str(m.get("content", "")) for m in seen)
    assert "warnings" in body and any("Skipped 1" in w for w in body["warnings"])


def test_chat_anonymous_attachments_warn(client, tmp_store):
    r = client.post("/api/chat", json={"message": "hello there friend", "attachment_ids": ["x"]})
    assert r.status_code == 200, r.text
    assert any("Sign in" in w for w in r.json().get("warnings", []))


# ------------------------------------------------------------ web search
_CANNED_HTML = """
<html><body><table>
<tr><td><a rel="nofollow" href="https://example.com/a">Alpha result</a></td></tr>
<tr><td class="result-snippet">Alpha snippet text</td></tr>
<tr><td><a rel="nofollow" href="https://example.com/b">Beta result</a></td></tr>
<tr><td class="result-snippet">Beta snippet text</td></tr>
</table></body></html>
"""


def _fake_ddg(monkeypatch):
    import httpx

    class _Resp:
        text = _CANNED_HTML

        def raise_for_status(self):
            pass

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp())


def test_websearch_disabled_by_default(client, auth_headers):
    r = client.get("/api/agent/websearch", params={"q": "nifty"}, headers=auth_headers)
    assert r.status_code == 501, r.text


def test_websearch_parses_canned_html(client, auth_headers, monkeypatch):
    monkeypatch.setenv("STOCKOS_AGENT_WEBSEARCH", "duckduckgo")
    _fake_ddg(monkeypatch)
    r = client.get("/api/agent/websearch", params={"q": "nifty outlook"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["query"] == "nifty outlook"
    assert [h["title"] for h in body["results"]] == ["Alpha result", "Beta result"]
    assert body["results"][0]["snippet"] == "Alpha snippet text"


def test_chat_websearch_source(client, auth_headers, monkeypatch):
    monkeypatch.setenv("STOCKOS_AGENT_WEBSEARCH", "duckduckgo")
    _fake_ddg(monkeypatch)
    seen = _capture_chat(monkeypatch)
    r = client.post("/api/chat", json={"message": "what is the market mood today", "websearch": True})
    assert r.status_code == 200, r.text
    assert "web-search" in r.json()["sources"]
    assert any("Alpha result" in str(m.get("content", "")) for m in seen)


# ---------------------------------------------------------------- skills
def test_skills_listed(client, auth_headers):
    r = client.get("/api/agent/skills", headers=auth_headers)
    assert r.status_code == 200, r.text
    names = {s["name"] for s in r.json()["skills"]}
    assert {"risk-discipline", "options-desk", "earnings-checklist"} <= names
    assert all("body" not in s for s in r.json()["skills"])  # bodies stay server-side


def test_chat_skill_block_and_unknown_warning(client, auth_headers, monkeypatch):
    seen = _capture_chat(monkeypatch)
    r = client.post("/api/chat", json={"message": "should i buy this stock", "skills": ["risk-discipline", "nope"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "skill:risk-discipline" in body["sources"]
    assert any("stop-loss" in str(m.get("content", "")) for m in seen)
    assert any("Unknown skill" in w for w in body.get("warnings", []))
