# IGA Access Review — Build Progress

## Phase 1 — Database & Infrastructure ✅
- PostgreSQL 16 running via Docker Compose
- All 7 tables created: departments, users, resources, entitlements,
  campaigns, entitlement_reviews, audit_logs
- Seed data loaded with 9 users, 8 resources, 13 entitlements
  (including intentional red flags: stale access, SoD violations, over-privilege)
- Config layer: Pydantic settings + LLM factory (Anthropic/OpenAI switchable)

---

## Phase 2 — Orchestrator Skeleton ✅
**Goal:** LangGraph StateGraph with stub agents. No real logic, no LLM calls, no DB queries.

### Files Created
| File | Purpose |
|------|---------|
| `orchestrator/state.py` | `CampaignState` TypedDict — single state object for the full pipeline |
| `agents/base.py` | `BaseAgent` abstract class with lazy `llm`, `log`, `db` properties |
| `agents/harvester.py` | `HarvesterAgent` stub → real in Phase 3 |
| `agents/risk_scorer.py` | `RiskScorerAgent` stub → real in Phase 3 |
| `agents/decision.py` | `DecisionAgent` stub → real in Phase 4 |
| `agents/notifier.py` | `NotifierAgent` stub → real in Phase 4 |
| `agents/audit.py` | `AuditAgent` stub → real in Phase 4 |
| `orchestrator/graph.py` | LangGraph StateGraph wiring all 6 nodes + conditional edge |
| `tests/test_graph.py` | End-to-end integration smoke test |

### Graph Flow
```
START → harvester → risk_scorer → decision
                                      ↓ (if any revoke)
                                  human_review → notifier → audit → END
                                      ↓ (no revokes)
                                  notifier → audit → END
```

### Key Design Decisions
- `CampaignState` list fields use `Annotated[list[dict], operator.add]` so
  LangGraph appends rather than overwrites on partial state updates
- `human_review_node` calls `interrupt()` (LangGraph) for HITL pause;
  returns `{}` as required by LangGraph after interrupt
- `MemorySaver` checkpointer for now (will swap to PostgreSQL in Phase 5)
- All `BaseAgent` properties are lazy — stubs work without DB or API keys

---

## Phase 3 — Harvester + Rule-Based Risk Scorer ✅
**Goal:** Replace Harvester and RiskScorer stubs with real implementations.
No LLM calls — pure SQLAlchemy + rule-based scoring.

### Files Modified / Created
| File | Change |
|------|--------|
| `agents/harvester.py` | Full SQLAlchemy implementation replacing stub |
| `agents/risk_scorer.py` | Rule-based scoring engine replacing stub |
| `tests/test_harvester.py` | 3 DB-backed integration tests |
| `tests/test_risk_scorer.py` | 7 pure-Python unit tests (no DB) |
| `tests/test_graph.py` | Added integration test + updated stub assertions |
| `pytest.ini` | Registered `stub` mark for graph skeleton tests |

### RiskScorerAgent Design — Scoring Rules

| Factor | Points |
|--------|--------|
| resource_sensitivity: critical | +40 |
| resource_sensitivity: high | +30 |
| resource_sensitivity: medium | +15 |
| resource_sensitivity: low | +5 |
| Never used (last_used is None) | +30 |
| Stale ≥ 180 days | +25 |
| Stale ≥ 90 days | +15 |
| Stale ≥ 30 days | +5 |
| SoD violation (Finance + IT in same user) | +20 |
| Role mismatch (Admin + Junior/Intern title) | +15 |
| **Maximum (capped)** | **100** |

### Actual Risk Scores for Seed Red-Flag Entitlements

| User | Resource | Score | Level | Flags |
|------|----------|-------|-------|-------|
| Bob Kumar | SAP Finance Admin | **80** | high | role_mismatch |
| Bob Kumar | HRIS Full Access | **70** | high | *(none — "Full Access" ≠ Admin)* |
| Dan Smith | AWS Production Admin | **80** | high | role_mismatch |
| Frank Lee | SAP Finance Admin | **75** | high | sod_violation |
| Frank Lee | AWS Production Admin | **60** | medium | sod_violation |

---

## Phase 4 — DecisionAgent + NotifierAgent + AuditAgent ✅
**Goal:** Complete the agent pipeline. First phase with real LLM calls.

### Files Modified / Created
| File | Change |
|------|--------|
| `agents/decision.py` | LLM per entitlement + EntitlementReview DB writes |
| `agents/notifier.py` | LLM per manager for email drafting (log, don't send) |
| `agents/audit.py` | Pure DB: Campaign→COMPLETED + per-decision AuditLog rows |
| `tests/test_decision.py` | 4 mocked unit tests (no DB, no API key) |
| `tests/test_notifier.py` | 3 mocked unit tests |
| `tests/test_audit.py` | 2 mocked unit tests |
| `tests/test_graph.py` | Extended integration test, resolved TODO status assertions |

### Agent Design Summaries

**DecisionAgent:**
- `self.llm.invoke([SystemMessage(...), HumanMessage(json.dumps(payload))])` per entitlement
- Safe JSON parse: defaults to `escalate / confidence=0.0` on failure or unknown value
- Single DB commit: all `EntitlementReview` rows + `Campaign.status=DECIDING` + 1 `AuditLog`
- `pending_human_review` = all revoke decisions with `human_decision=None, human_reviewer=None`

**NotifierAgent:**
- Groups decisions by `manager_email` using `defaultdict`
- One LLM call per manager (compact payload: user_name, resource_name, role, ai_decision, ai_reasoning, risk_level)
- Parse failure for one manager → `log.error` + `continue` (campaign not aborted)
- No DB writes; returns `notified=True` even on partial failures

**AuditAgent:**
- No LLM — pure DB
- Campaign → `COMPLETED` + `completed_at`
- One `AuditLog(event="entitlement_decision")` per decision
- One `AuditLog(event="campaign_complete")` with full summary
- Single commit; returns `status="completed", audit_complete=True`

### Test Results

**Step 1 — Mocked unit tests (no DB, no API key):**
```
9 passed in 0.73s

tests/test_decision.py::test_decision_approve                       PASSED
tests/test_decision.py::test_decision_revoke_goes_to_pending        PASSED
tests/test_decision.py::test_decision_handles_bad_json              PASSED
tests/test_decision.py::test_decision_handles_invalid_decision_value PASSED
tests/test_notifier.py::test_notifier_groups_by_manager             PASSED
tests/test_notifier.py::test_notifier_skips_null_manager            PASSED
tests/test_notifier.py::test_notifier_continues_on_parse_error      PASSED
tests/test_audit.py::test_audit_marks_campaign_complete             PASSED
tests/test_audit.py::test_audit_writes_one_log_per_decision         PASSED
```

**Step 2 — Full suite (requires Docker PG + real API key in .env):**
```
19 passed, 2 failed

19 PASSED — all DB-only and mocked tests
2 FAILED  — tests/test_graph.py::test_campaign_runs_end_to_end
            tests/test_graph.py::test_graph_with_real_harvester_and_scorer

Failure reason: ANTHROPIC_API_KEY=your_key_here (placeholder not replaced)
Fix: set a real key in .env and re-run pytest tests/ -v
```

### LLM Decisions for Red-Flag Entitlements
*(Requires real API key — predictions based on risk scores and system prompt rules)*

| User | Resource | Score | Predicted Decision | Basis |
|------|----------|-------|--------------------|-------|
| Bob Kumar | SAP Finance Admin | 80 (high + role_mismatch) | **REVOKE** | Stale 180d + junior Admin |
| Bob Kumar | HRIS Full Access | 70 (high, never used) | **REVOKE** | Never used critical resource |
| Dan Smith | AWS Production Admin | 80 (high + role_mismatch) | **REVOKE** | Stale 200d + junior Admin |
| Frank Lee | SAP Finance Admin | 75 (high + sod_violation) | **REVOKE/ESCALATE** | SoD violation, 90d stale |
| Frank Lee | AWS Production Admin | 60 (medium + sod_violation) | **ESCALATE** | SoD flag but recently used |

*Actual decisions will be recorded here after running with a valid API key.*

---

## Phase 5 — PostgresSaver, FastAPI & HITL Resume ✅
**Goal:** Persistent state across restarts + full REST API + verified interrupt→resume flow.

### Files Modified / Created
| File | Change |
|------|--------|
| `requirements.txt` | Added `psycopg[binary]>=3.1.0` + `langgraph-checkpoint-postgres>=2.0.0` |
| `orchestrator/graph.py` | Swapped `MemorySaver` → `PostgresSaver`; added `get_campaign_state`, `resume_campaign`, `_merge_human_decisions`; implemented full `human_review_node` |
| `api/main.py` | FastAPI app setup + router include |
| `api/routes.py` | 5 endpoints: GET /health, POST /campaigns, GET /campaigns/{id}, GET /campaigns/{id}/review, POST /campaigns/{id}/resume |
| `tests/test_api.py` | 9 mocked unit tests (no graph, no DB) |
| `tests/test_hitl_flow.py` | 1 full interrupt→resume integration test |
| `Dockerfile` | python:3.11-slim image for API service |

### Checkpointer Design
- **`PostgresSaver`** (sync, `langgraph-checkpoint-postgres`) replaces `MemorySaver`
- Connection uses `autocommit=True, prepare_threshold=0, row_factory=dict_row` —
  required for `CREATE INDEX CONCURRENTLY` in `checkpointer.setup()`
- psycopg v3 (`psycopg[binary]`) is used; psycopg2 is kept for SQLAlchemy
- Thread ID = `campaign_id` — same value as `Campaign.langgraph_thread_id`

### API Endpoints
| Method | Path | Status | Description |
|--------|------|--------|-------------|
| GET | `/health` | 200 | Liveness check |
| POST | `/campaigns` | 202 | Start campaign (background task) |
| GET | `/campaigns/{id}` | 200/404 | Poll status |
| GET | `/campaigns/{id}/review` | 200/404 | Get pending HITL items |
| POST | `/campaigns/{id}/resume` | 202/404/409/422 | Submit human decisions |

### HITL Resume Flow
1. `POST /campaigns` → generates `uuid4` campaign_id, fires `run_campaign()` in background
2. Graph runs until `human_review_node` calls `interrupt()` → state persisted to PostgreSQL
3. `GET /campaigns/{id}/review` → caller retrieves `pending_human_review` items
4. `POST /campaigns/{id}/resume` → validates decisions, calls `resume_campaign()` in background
5. `resume_campaign()` calls `graph.update_state(..., as_node="human_review")` then `graph.invoke(None, config)`
6. Graph resumes from `human_review_node` → notifier → audit → COMPLETED

### Test Results
```
31 passed in 65s

tests/test_api.py            9 passed  (mocked, no graph/DB)
tests/test_hitl_flow.py      1 passed  (full interrupt→resume with real Ollama + PG)
tests/test_graph.py          2 passed
tests/test_harvester.py      3 passed
tests/test_risk_scorer.py    7 passed
tests/test_decision.py       4 passed
tests/test_notifier.py       3 passed
tests/test_audit.py          2 passed
```

### HITL Flow Test Verification
`test_full_hitl_flow` confirmed end-to-end with `llama3.1:8b`:
- Graph paused at `human_review_node` with `status="deciding"`
- `get_campaign_state()` retrieved persisted state from PostgreSQL checkpointer
- `resume_campaign()` with `human_decision="approve"` for all revokes
- Final `status="completed"`, `audit_complete=True`, `notified=True`
- `Campaign.status == COMPLETED` and `completed_at` set in DB
