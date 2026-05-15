# IGA Access Review — Multi-Agent System

## Project overview
Autonomous access certification system using LangGraph multi-agent 
architecture. Runs end-to-end access review campaigns with HITL checkpoints.

## Tech stack
- Python 3.11, LangGraph, LangChain
- PostgreSQL (IGA data + LangGraph state store)
- FastAPI, Celery, Redis
- LangSmith (observability)
- Docker Compose
- LLM: Claude (Anthropic) or OpenAI — switchable via config/llm_config.py

## LLM providers
Switch provider with one line in .env — no code changes needed.
| Provider  | LLM_MODEL example            | Key needed |
|-----------|------------------------------|------------|
| anthropic | claude-haiku-4-5-20251001         | Yes        |
| openai    | gpt-4o-mini                  | Yes        |
| google    | gemini-2.0-flash             | Yes (free) |
| ollama    | llama3.1:8b                  | No         |

Verify LLM works before running any phase:
    python scripts/verify_llm.py

## Project structure
agents/          # harvester, risk_scorer, decision, notifier, audit
orchestrator/    # LangGraph state graph
api/             # FastAPI endpoints
db/              # SQLAlchemy models + seed data
config/          # settings.py, llm_config.py
tests/           # pytest unit tests per agent

## Key commands
- Start services:   docker-compose up -d
- Run API:          uvicorn api.main:app --reload
- Run worker:       celery -A worker.celery_app worker
- Run tests:        pytest tests/ -v
- DB migrate:       alembic upgrade head
- DB seed:          python db/seed.py

## Code conventions
- Type hints on all functions
- Each agent is a class with a single `run(state: CampaignState) -> CampaignState` method
- Never mutate state in place — always return a new state dict
- All LLM calls go through config/llm_config.py, never instantiate models directly
- Use structlog for logging, not print()

## Evaluation
Run decision accuracy evaluation against ground truth:
    python scripts/evaluate_decisions.py

## Testing rules
- No mocking the core agent logic — test with real DB fixtures
- Each agent must have at least one happy path and one failure test