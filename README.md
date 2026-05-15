# IGA Access Review

Autonomous access certification system using LangGraph multi-agent architecture.

---

## The Problem

Enterprise access certification — reviewing who has access to what and whether that access is still appropriate — is typically rubber-stamped by managers who lack the context or time to make good decisions. Solutions like SailPoint and Saviynt provide workflows but still depend on humans reviewing hundreds of entitlements manually. This project automates the review using LLM-driven agents that understand IGA policy, score risk deterministically, and make approve/revoke/escalate decisions with a human-in-the-loop checkpoint for the highest-risk revokes.

---

## Architecture

```
FastAPI
  │
  ├── POST /campaigns              ← Start campaign (background task)
  ├── GET  /campaigns/{id}         ← Poll status
  ├── GET  /campaigns/{id}/review  ← Get pending HITL items
  └── POST /campaigns/{id}/resume  ← Submit human decisions
       │
       ▼
LangGraph Orchestrator (PostgresSaver checkpoint)
       │
  ┌────┴────────────────────────────────────────────┐
  ▼                                                 ▼
HarvesterAgent          (on resume after human review)
  │  SQLAlchemy JOIN                  │
  │  13 entitlements                  │
  ▼                                   │
RiskScorerAgent                       │
  │  Rule-based scoring               │
  │  0–100 per entitlement            │
  ▼                                   │
DecisionAgent ──────────────────► [HITL Checkpoint]
  │  LLM per entitlement             interrupt()
  │  approve / revoke / escalate      │
  │  retry on transient failures      │ resume_campaign()
  ▼                                   │
NotifierAgent ◄─────────────────────-─┘
  │  LLM email draft per manager
  ▼
AuditAgent
  │  Campaign → COMPLETED
  │  AuditLog per decision
  ▼
PostgreSQL
```

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| LLM orchestration | LangGraph 1.x, LangChain |
| LLM providers | Anthropic / OpenAI / Google Gemini / Ollama |
| API | FastAPI |
| Database | PostgreSQL 16 |
| State persistence | LangGraph PostgresSaver |
| Observability | LangSmith |
| Testing | pytest (33 tests) |
| Infrastructure | Docker Compose |

---

## Quick Start

```bash
git clone <repo>
cd iga-access-review

# Copy and configure environment
cp .env.example .env
# Edit .env — set LLM_PROVIDER and the matching API key
# (or use LLM_PROVIDER=ollama with Ollama running locally)

# Start infrastructure
docker-compose up -d db redis

# Install dependencies
pip install -r requirements.txt

# Create database tables
alembic upgrade head

# Load seed data (9 users, 8 resources, 13 entitlements)
python -m db.seed

# Verify LLM is working
python scripts/verify_llm.py

# Start API
uvicorn api.main:app --reload
```

---

## API Usage

### Health check
```bash
curl http://localhost:8000/health
# {"status":"ok","service":"iga-access-review"}
```

### Observability status
```bash
curl http://localhost:8000/observability/status
# {"langsmith_tracing":false,"langsmith_project":"iga-access-review",...}
```

### Start a campaign
```bash
curl -X POST http://localhost:8000/campaigns \
  -H "Content-Type: application/json" \
  -d '{"campaign_name": "Q2 2026 Access Review"}'
# 202 {"campaign_id":"abc-123","status":"created","message":"..."}
```

### Poll campaign status
```bash
curl http://localhost:8000/campaigns/abc-123
# {"campaign_id":"abc-123","status":"deciding","entitlement_count":13,...}
```

### Get pending human review items
```bash
curl http://localhost:8000/campaigns/abc-123/review
# {"pending_count":4,"pending_human_review":[...]}
```

### Submit human decisions and resume
```bash
curl -X POST http://localhost:8000/campaigns/abc-123/resume \
  -H "Content-Type: application/json" \
  -d '{
    "decisions": [
      {
        "entitlement_id": "eb147c36-...",
        "human_decision": "revoke",
        "human_reviewer": "alice@acme.com"
      }
    ]
  }'
# 202 {"campaign_id":"abc-123","message":"Human decisions submitted. Campaign resuming.",...}
```

---

## Running a Full Campaign (Step by Step)

```bash
# 1. Start a campaign
CAMPAIGN=$(curl -s -X POST http://localhost:8000/campaigns \
  -H "Content-Type: application/json" \
  -d '{"campaign_name":"Manual Test"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['campaign_id'])")

echo "Campaign ID: $CAMPAIGN"

# 2. Poll until status is "deciding" or "completed"
curl http://localhost:8000/campaigns/$CAMPAIGN

# 3. If status == "deciding", get the items awaiting review
curl http://localhost:8000/campaigns/$CAMPAIGN/review

# 4. Submit human decisions for each pending entitlement
curl -X POST http://localhost:8000/campaigns/$CAMPAIGN/resume \
  -H "Content-Type: application/json" \
  -d '{"decisions":[{"entitlement_id":"<id>","human_decision":"revoke","human_reviewer":"you@acme.com"}]}'

# 5. Poll until status == "completed"
curl http://localhost:8000/campaigns/$CAMPAIGN
```

---

## Running Tests

```bash
# Fast — no DB or LLM required (mocked)
pytest tests/test_risk_scorer.py tests/test_decision.py \
       tests/test_notifier.py tests/test_audit.py tests/test_api.py -v

# Full suite — requires Docker PostgreSQL + Ollama (or API key)
pytest tests/ -v

# Evaluation — measure decision accuracy vs ground truth
python scripts/evaluate_decisions.py
```

**Test results (Phase 6):**
```
33 passed

tests/test_api.py            10 tests  (mocked, no graph/DB)
tests/test_decision.py        5 tests  (mocked, includes retry test)
tests/test_notifier.py        3 tests  (mocked)
tests/test_audit.py           2 tests  (mocked)
tests/test_risk_scorer.py     7 tests  (pure Python, no DB)
tests/test_harvester.py       3 tests  (DB-backed)
tests/test_graph.py           2 tests  (end-to-end, HITL-aware)
tests/test_hitl_flow.py       1 test   (full interrupt→resume integration)
```

---

## Project Structure

```
iga-access-review/
│
├── agents/                   # Agent implementations
│   ├── base.py               # BaseAgent with lazy llm, log, db properties
│   ├── harvester.py          # SQLAlchemy JOIN → 13 entitlement dicts
│   ├── risk_scorer.py        # Rule-based scoring (0–100)
│   ├── decision.py           # LLM per entitlement (approve/revoke/escalate)
│   ├── notifier.py           # LLM email drafts grouped by manager
│   └── audit.py              # Pure DB: Campaign→COMPLETED + AuditLog rows
│
├── orchestrator/
│   ├── state.py              # CampaignState TypedDict (Annotated list reducers)
│   └── graph.py              # LangGraph StateGraph + PostgresSaver checkpointer
│
├── api/
│   ├── main.py               # FastAPI app setup + LangSmith tracing init
│   └── routes.py             # 6 endpoints (health, observability, campaigns, HITL)
│
├── config/
│   ├── settings.py           # Pydantic Settings (all env vars)
│   ├── llm_config.py         # get_llm() factory — 4 providers
│   └── tracing.py            # init_tracing() — set LangSmith vars before imports
│
├── db/
│   ├── models.py             # SQLAlchemy ORM (7 tables, 3 enums)
│   ├── session.py            # SessionLocal, get_db()
│   └── seed.py               # Seed data with intentional red-flags
│
├── scripts/
│   ├── verify_llm.py         # Sanity check LLM before running phases
│   └── evaluate_decisions.py # Decision accuracy vs ground truth
│
├── tests/                    # pytest unit + integration tests
├── .env.example              # Template — copy to .env
├── docker-compose.yml        # PostgreSQL 16, Redis 7, API, worker
├── Dockerfile                # python:3.11-slim image
└── requirements.txt
```

---

## Design Decisions

**Why LangGraph?** LangGraph provides stateful, resumable, observable graph execution — exactly what a multi-agent pipeline with HITL checkpoints requires. The `interrupt()` primitive lets the graph pause at a node, serialize full state to PostgreSQL, and resume days later after a human reviewer acts. Alternative approaches (plain async queues, Celery chains) require bespoke state management that LangGraph provides natively. LangSmith integration gives per-agent trace visibility with zero instrumentation code.

**Why PostgresSaver?** The HITL pattern only works if state survives server restarts. `MemorySaver` (used in early development) loses all state when the process exits. `PostgresSaver` from `langgraph-checkpoint-postgres` writes LangGraph checkpoint tables to the same PostgreSQL instance used for IGA data — no additional infrastructure. The `thread_id = campaign_id` pattern means a campaign can be paused for days, the server can be redeployed, and `resume_campaign(campaign_id, decisions)` picks up exactly where it left off.

**Why rule-based scoring + LLM decisions?** Risk scoring is deterministic: staleness, resource sensitivity, SoD violations, and role mismatches have objective, auditable rules with no LLM non-determinism. LLM judgment is reserved for the final approve/revoke/escalate decision where contextual reasoning matters — "is a staff engineer running GitHub Org Admin unusual?" The two-stage design means scoring results are reproducible and auditable, while decisions benefit from the LLM's ability to reason about nuanced combinations of factors.

---

## What This Demonstrates

- **Stateful multi-agent orchestration** — LangGraph StateGraph with 6 nodes, conditional routing, and Annotated state reducers for append-only list fields
- **Production HITL pattern** — `interrupt()` / `resume_campaign()` with PostgreSQL-persisted state, REST API integration, and a full end-to-end integration test
- **Provider-agnostic LLM design** — four providers (Anthropic, OpenAI, Google Gemini, Ollama) switchable via a single `.env` line with no agent code changes; retry logic handles transient failures
- **Enterprise IGA domain knowledge** — accurate risk scoring rules (SoD detection, staleness tiers, role-mismatch detection), ground-truth evaluation (92.3% accuracy, 100% recall on revokes), and a realistic seed dataset with intentional policy violations
