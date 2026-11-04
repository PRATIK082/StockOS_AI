"""Optional Agno + LiteLLM agent runtime (P5-a).

Opt-in via ``STOCKOS_AGENT_RUNTIME=agno`` (default: ``legacy``). When enabled
*and* the ``agno`` + ``litellm`` packages are importable, a StockOS agent's
evidence pass (its normal ``run()``) is followed by one Agno tool-calling pass
over that evidence, with the P5-b order tools (``preview_order`` read-only,
``place_order`` approval-gated) available to the model. The returned
``AgentResult`` keeps the original agent name, data, confidence and sources;
only ``content`` may be refined, and ``data["runtime"]`` records ``"agno"``.

Every failure mode falls back to the legacy result, so enabling the flag can
never break an agent: missing deps, unreachable model, empty reply, or any
Agno exception all return the untouched legacy ``AgentResult``.

Model selection: ``STOCKOS_AGENT_MODEL`` env, else the configured
``llm_default_model``, else ``qwen3:14b`` (local Ollama default, verified
with tool-calling). Bare names against an Ollama base URL are mapped through
:func:`litellm_model_id`.
"""

from __future__ import annotations

import importlib.util
import json
import os
from typing import Any

from app.core.logging import get_logger
from app.services.agents.base import Agent, AgentContext, AgentResult
from app.services.llm.providers.litellm_provider import litellm_model_id

logger = get_logger("agents.runtime_agno")

RUNTIME_ENV_VAR = "STOCKOS_AGENT_RUNTIME"
MODEL_ENV_VAR = "STOCKOS_AGENT_MODEL"
DEFAULT_LOCAL_MODEL = "qwen3:14b"


def current_runtime() -> str:
    """Active agent runtime name: ``"agno"`` when opted in, else ``"legacy"``."""
    return (os.environ.get(RUNTIME_ENV_VAR, "legacy") or "legacy").strip().lower() or "legacy"


def is_agno_available() -> bool:
    """True when both optional runtime packages are importable."""
    return importlib.util.find_spec("agno") is not None and (
        importlib.util.find_spec("litellm") is not None
    )


def agent_model_id() -> str:
    """Resolve the LiteLLM model id for the Agno pass (never empty)."""
    from app.core.config import settings

    raw = (
        (os.environ.get(MODEL_ENV_VAR) or "").strip()
        or (settings.llm_default_model or "").strip()
        or DEFAULT_LOCAL_MODEL
    )
    return litellm_model_id(raw, settings.ollama_base_url)


async def _preview_wrapper(symbol: str, side: str, quantity: float) -> str:
    """Read-only order preview tool for the Agno agent (no user needed)."""
    from app.services.agents.tools import AgentToolError, run_tool

    try:
        result = await run_tool(
            "preview_order",
            {"symbol": symbol, "side": side, "quantity": quantity},
            user_id="agno-runtime",
        )
    except AgentToolError as exc:
        return f"Preview rejected: {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"Preview failed: {exc}"
    return json.dumps(result, default=str)


def _make_place_wrapper(user_id: str | None):
    """Build the approval-gated place_order tool (never raises into Agno)."""

    async def place_order(
        symbol: str,
        side: str,
        quantity: float,
        price: float | None = None,
        order_type: str = "MARKET",
    ) -> str:
        """Place an order (approval-gated) or file it for human review."""
        from app.services.agents.tools import AgentToolError, run_tool

        if not user_id:
            return (
                "Order NOT placed: no user context on this run. Ask the user "
                "to place it from the Action Center or Trading page."
            )
        args: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "order_type": order_type,
        }
        if price is not None:
            args["price"] = price
        try:
            result = await run_tool("place_order", args, user_id=user_id)
        except AgentToolError as exc:
            return f"Order rejected: {exc}"
        except Exception as exc:  # noqa: BLE001
            return f"Order tool failed: {exc}"
        return json.dumps(result, default=str)

    return place_order


def _build_agno_agent(agent: Agent, user_id: str | None):
    """Construct the Agno agent (imports agno lazily; may raise)."""
    from agno.agent import Agent as AgnoAgent
    from agno.models.litellm import LiteLLM

    from app.core.config import settings

    return AgnoAgent(
        model=LiteLLM(id=agent_model_id(), api_base=settings.ollama_base_url),
        tools=[_preview_wrapper, _make_place_wrapper(user_id)],
        instructions=(
            f"You are {agent.display_name or agent.name}. "
            f"{agent.description} "
            "Refine the provided evidence readout briefly and honestly; never "
            "invent prices or levels not present in the evidence. You may call "
            "preview_order for a read-only quote + risk check. place_order "
            "either fills (paper mode) or files a human approval item — "
            "announce which happened."
        ),
    )


async def run_agent(
    agent: Agent, ctx: AgentContext, *, user_id: str | None = None
) -> AgentResult:
    """Run a StockOS agent under the configured runtime.

    Legacy (default) returns ``agent.run(ctx)`` untouched. The Agno runtime
    runs the same evidence pass first, then refines it with one Agno
    tool-calling pass, falling back to the legacy result on any failure.
    """
    legacy = await agent.run(ctx)
    if current_runtime() != "agno":
        return legacy
    if not is_agno_available():
        logger.warning("STOCKOS_AGENT_RUNTIME=agno but agno/litellm are not installed; using legacy")
        return legacy
    try:
        agno_agent = _build_agno_agent(agent, user_id)
        prompt = json.dumps(
            {
                "task": ctx.task,
                "symbol": ctx.symbol,
                "evidence": legacy.content,
            },
            default=str,
        )
        resp = await agno_agent.arun(prompt)
        text = (getattr(resp, "content", None) or "").strip()
        if not text:
            return legacy
        data = dict(legacy.data)
        data["runtime"] = "agno"
        return AgentResult(
            content=text,
            data=data,
            confidence=legacy.confidence,
            sources=list(legacy.sources),
            agent=legacy.agent or agent.name,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Agno runtime failed for agent '%s', using legacy: %s", agent.name, exc)
        return legacy
