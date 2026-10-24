# StockOS AI

StockOS AI is a local-first stock market research and paper-trading platform.
It combines market data, technical analysis, options analytics, AI-assisted
research, risk controls, and a multi-agent autopilot that runs entirely in
paper mode by default.

## Features

- Market data and charts for Indian and US symbols
- Technical indicators and signal markers
- AI research and prediction views
- Options chain analysis and strategy helpers
- Paper trading with risk limits and kill switch
- AI agentic analysis and autopilot missions
- Learning memory for agent insights

## Requirements

- Python 3.12+
- Node.js 18+
- `uv` (recommended) or `pip`
- Optional local LLM runtime such as Ollama

## Quick start

Backend:

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open:

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API docs: http://localhost:8000/docs

## Optional environment

Copy `backend/.env.example` to `backend/.env` and configure providers, keys, and
database settings. Copy `frontend/.env.local.example` if present, or create
`frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Safety notes

- Default execution mode is `PAPER`. No live orders are sent unless
  `execution_mode=LIVE_ENABLED` and broker credentials are configured.
- Risk limits are enforced by the backend risk engine.
- Never commit `.env`, API keys, database files, or local runtime data.

## Third-party services and licenses

This project uses third-party market-data and LLM providers. Their APIs and
licenses remain with their respective owners. See each provider's terms before
enabling live or paid usage.

- Yahoo Finance (yfinance) - market data
- TradingView scanner endpoints - Indian option chains
- NSE public endpoints - Indian options (may be access-limited)
- Ollama / LM Studio / llama.cpp - local LLM runtimes
- OpenAI-compatible providers - optional cloud/local LLM endpoints

## License

This project is for educational and research purposes. Review all third-party
licenses before redistribution or commercial use.
