"""Ollama provider.

Ollama exposes an OpenAI-compatible endpoint at `/v1`, plus a native
`/api/tags` endpoint we use for model auto-detection.
"""

from __future__ import annotations

import httpx

from app.services.llm.providers.openai_compat import OpenAICompatProvider


class OllamaProvider(OpenAICompatProvider):
    name = "ollama"

    def __init__(self, base_url: str, default_model: str = "") -> None:
        super().__init__(base_url=f"{base_url.rstrip('/')}/v1", default_model=default_model)
        self._base = base_url.rstrip("/")

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self._base}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                models = [m["name"] for m in data.get("models", [])]
                # Also surface OpenAI-compatible ids from /v1/models for parity.
                try:
                    openai_ids = await super().list_models()
                    models.extend(openai_ids)
                except Exception:  # noqa: BLE001
                    pass
                return list(dict.fromkeys(models))
        except Exception:  # noqa: BLE001
            return [self.default_model] if self.default_model else []
