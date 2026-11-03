"""Tests for P5-a: LiteLLM provider + optional Agno agent runtime.

All Agno/LiteLLM interactions are faked (no network, no model needed). Only
module importability of the real ``agno``/``litellm`` packages is probed, and
even that is monkeypatched for the unavailable-dep paths.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from app.services.agents.base import Agent, AgentContext, AgentResult


class _StubAgent(Agent):
    name = "stub"
    display_name = "Stub Agent"
    description = "Deterministic stub for runtime tests."

    async def run(self, ctx: AgentContext) -> AgentResult:
        return AgentResult(
            content="legacy evidence",
            data={"k": 1},
            confidence=0.7,
            sources=["s"],
            agent=self.name,
        )


# --- litellm_model_id mapping (pure) ---------------------------------------


def test_litellm_model_id_mapping() -> None:
    from app.services.llm.providers.litellm_provider import litellm_model_id

    assert (
        litellm_model_id("ministral-3:14b", "http://localhost:11434")
        == "ollama/ministral-3:14b"
    )
    assert (
        litellm_model_id("ollama/qwen3:14b", "http://localhost:11434")
        == "ollama/qwen3:14b"
    )
    assert litellm_model_id("gpt-4o-mini", "https://api.openai.com/v1") == "gpt-4o-mini"
    assert litellm_model_id("", "http://localhost:11434") == ""


def test_gateway_builds_litellm_provider() -> None:
    from app.services.llm.gateway import SUPPORTED_PROVIDERS, build_provider

    assert "litellm" in SUPPORTED_PROVIDERS
    assert build_provider("litellm").name == "litellm"


# --- LiteLLMProvider with a fake litellm module ------------------------------


def _fake_litellm_module(captured: dict, chunks: list | None = None):
    mod = types.ModuleType("litellm")

    class _Msg:
        def __init__(self, content: str | None) -> None:
            self.content = content

    class _Choice:
        def __init__(self, content: str | None) -> None:
            self.message = _Msg(content)
            self.delta = _Msg(content)

    async def acompletion(**kwargs: Any):
        captured.update(kwargs)
        if kwargs.get("stream"):
            async def _gen():
                for text in (chunks or []):
                    yield types.SimpleNamespace(choices=[_Choice(text)])

            return _gen()
        return types.SimpleNamespace(choices=[_Choice("hello world")])

    mod.acompletion = acompletion  # type: ignore[attr-defined]
    return mod


def test_provider_chat_uses_fake_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from app.services.llm.providers import ChatMessage
    from app.services.llm.providers.litellm_provider import LiteLLMProvider

    captured: dict = {}
    monkeypatch.setitem(sys.modules, "litellm", _fake_litellm_module(captured))
    prov = LiteLLMProvider(
        api_base="http://localhost:11434", default_model="ministral-3:14b"
    )
    text = asyncio.run(
        prov.chat(
            [ChatMessage(role="user", content="hi")],
            temperature=0.1,
        )
    )
    assert text == "hello world"
    assert captured["model"] == "ollama/ministral-3:14b"
    assert captured["api_base"] == "http://localhost:11434"
    assert captured["temperature"] == 0.1
    assert captured["messages"] == [{"role": "user", "content": "hi"}]


def test_provider_chat_missing_dep_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from app.services.llm.providers.litellm_provider import LiteLLMProvider

    monkeypatch.setitem(sys.modules, "litellm", None)
    prov = LiteLLMProvider(default_model="m")
    with pytest.raises(RuntimeError):
        asyncio.run(prov.chat([{"role": "user", "content": "hi"}]))


def test_provider_stream_yields_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from app.services.llm.providers import ChatMessage
    from app.services.llm.providers.litellm_provider import LiteLLMProvider

    captured: dict = {}
    monkeypatch.setitem(
        sys.modules, "litellm", _fake_litellm_module(captured, chunks=["he", "llo"])
    )
    prov = LiteLLMProvider(default_model="m")

    async def _collect() -> str:
        parts = []
        async for piece in prov.stream_chat([ChatMessage(role="user", content="hi")]):
            parts.append(piece)
        return "".join(parts)

    assert asyncio.run(_collect()) == "hello"


# --- runtime_agno ------------------------------------------------------------


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_run_agent_legacy_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.agents import runtime_agno

    monkeypatch.delenv("STOCKOS_AGENT_RUNTIME", raising=False)
    out = _run(runtime_agno.run_agent(_StubAgent(), AgentContext(task="t")))
    assert out.content == "legacy evidence"
    assert "runtime" not in out.data


def test_run_agent_unknown_runtime_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.agents import runtime_agno

    monkeypatch.setenv("STOCKOS_AGENT_RUNTIME", "bogus")
    out = _run(runtime_agno.run_agent(_StubAgent(), AgentContext(task="t")))
    assert out.content == "legacy evidence"


def test_run_agent_agno_but_deps_missing_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.agents import runtime_agno

    monkeypatch.setenv("STOCKOS_AGENT_RUNTIME", "agno")
    monkeypatch.setattr(runtime_agno, "is_agno_available", lambda: False)
    out = _run(runtime_agno.run_agent(_StubAgent(), AgentContext(task="t")))
    assert out.content == "legacy evidence"
    assert "runtime" not in out.data


class _FakeAgnoAgent:
    instances: list["_FakeAgnoAgent"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        _FakeAgnoAgent.instances.append(self)

    async def arun(self, prompt: str):
        assert "legacy evidence" in prompt
        return types.SimpleNamespace(content="  refined readout  ")


class _FakeLiteLLM:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


def test_run_agent_agno_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.agents import runtime_agno

    _FakeAgnoAgent.instances.clear()
    monkeypatch.setenv("STOCKOS_AGENT_RUNTIME", "agno")
    monkeypatch.setenv("STOCKOS_AGENT_MODEL", "test-model")
    monkeypatch.setattr(runtime_agno, "is_agno_available", lambda: True)
    monkeypatch.setattr("agno.agent.Agent", _FakeAgnoAgent)
    monkeypatch.setattr("agno.models.litellm.LiteLLM", _FakeLiteLLM)

    out = _run(runtime_agno.run_agent(_StubAgent(), AgentContext(task="t")))

    assert out.content == "refined readout"
    assert out.agent == "stub"
    assert out.data["k"] == 1
    assert out.data["runtime"] == "agno"
    assert out.confidence == 0.7
    assert out.sources == ["s"]
    assert len(_FakeAgnoAgent.instances) == 1
    built = _FakeAgnoAgent.instances[0].kwargs
    assert len(built["tools"]) == 2
    assert "Stub Agent" in built["instructions"]


def test_run_agent_agno_exception_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.agents import runtime_agno

    class _Boom(_FakeAgnoAgent):
        async def arun(self, prompt: str):
            raise RuntimeError("model down")

    monkeypatch.setenv("STOCKOS_AGENT_RUNTIME", "agno")
    monkeypatch.setattr(runtime_agno, "is_agno_available", lambda: True)
    monkeypatch.setattr("agno.agent.Agent", _Boom)
    monkeypatch.setattr("agno.models.litellm.LiteLLM", _FakeLiteLLM)

    out = _run(runtime_agno.run_agent(_StubAgent(), AgentContext(task="t")))
    assert out.content == "legacy evidence"
    assert "runtime" not in out.data


def test_place_wrapper_without_user_never_touches_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.agents import runtime_agno

    async def _nope(*args: Any, **kwargs: Any):  # pragma: no cover
        raise AssertionError("run_tool must not be called without a user")

    monkeypatch.setattr("app.services.agents.tools.run_tool", _nope)
    place = runtime_agno._make_place_wrapper(None)
    msg = _run(place("NSE:RELIANCE", "BUY", 1))
    assert "NOT placed" in msg


def test_place_wrapper_surfaces_validation_rejection() -> None:
    from app.services.agents import runtime_agno

    place = runtime_agno._make_place_wrapper("some-user")
    msg = _run(place("", "BUY", 1))
    assert "symbol is required" in msg.lower()


def test_orchestrator_routes_through_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.agents import runtime_agno
    from app.services.agents.base import AgentResult
    from app.services.agents.orchestrator import Orchestrator

    seen: list[str] = []

    async def _fake_run(agent: Agent, ctx: AgentContext, **kwargs: Any) -> AgentResult:
        seen.append(agent.name)
        return AgentResult(content="via-runtime", agent=agent.name)

    monkeypatch.setattr(runtime_agno, "run_agent", _fake_run)
    out = _run(Orchestrator().run(task="hello", intent="chat"))
    assert seen == ["chat"]
    assert out["answer"] == "via-runtime"
