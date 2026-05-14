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
| `agents/harvester.py` | `HarvesterAgent` stub — returns empty entitlements |
| `agents/risk_scorer.py` | `RiskScorerAgent` stub — returns empty scored_entitlements |
| `agents/decision.py` | `DecisionAgent` stub — returns empty decisions |
| `agents/notifier.py` | `NotifierAgent` stub — sets notified=False |
| `agents/audit.py` | `AuditAgent` stub — sets audit_complete=False |
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
- `MemorySaver` checkpointer for Phase 2 (in-process, no PostgreSQL needed)
- All `BaseAgent` properties are lazy — stubs work without DB or API keys

### Test Results
```
tests/test_graph.py::test_campaign_runs_end_to_end PASSED   [1.91s]
```

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

### HarvesterAgent Design
- Single 4-table JOIN: `Entitlement → User → Resource → Department`
  plus `OUTERJOIN` to aliased `User` for nullable `manager_id`
- Creates `Campaign` record + 2 `AuditLog` entries per run
- Full try/except/finally with rollback on error, always closes session
- Returns 13 active entitlements from seed data

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

Risk level thresholds (≥): `81=critical`, `61=high`, `31=medium`, `0=low`

### Actual Risk Scores for Seed Red-Flag Entitlements

| User | Resource | Score | Level | Flags |
|------|----------|-------|-------|-------|
| Bob Kumar | SAP Finance Admin | **80** | high | role_mismatch |
| Bob Kumar | HRIS Full Access | **70** | high | *(none — "Full Access" ≠ Admin)* |
| Dan Smith | AWS Production Admin | **80** | high | role_mismatch |
| Frank Lee | SAP Finance Admin | **75** | high | sod_violation |
| Frank Lee | AWS Production Admin | **60** | medium | sod_violation |

### Test Results
```
12 passed in 0.66s

tests/test_graph.py::test_campaign_runs_end_to_end            PASSED
tests/test_graph.py::test_graph_with_real_harvester_and_scorer PASSED
tests/test_harvester.py::test_harvester_returns_all_active_entitlements PASSED
tests/test_harvester.py::test_harvester_creates_campaign_record PASSED
tests/test_harvester.py::test_harvester_creates_audit_logs PASSED
tests/test_risk_scorer.py::test_risk_scorer_scores_all_entitlements PASSED
tests/test_risk_scorer.py::test_critical_resource_never_used_scores_high PASSED
tests/test_risk_scorer.py::test_sod_violation_detected PASSED
tests/test_risk_scorer.py::test_role_mismatch_detected PASSED
tests/test_risk_scorer.py::test_score_capped_at_100 PASSED
tests/test_risk_scorer.py::test_risk_scorer_handles_empty_entitlements PASSED
tests/test_risk_scorer.py::test_risk_level_boundaries PASSED
```

---

## Phase 4 — DecisionAgent (Planned)
Replace `DecisionAgent` stub with real LLM-driven decision making:
- Iterate `state["scored_entitlements"]`
- Call Claude (via `self.llm`) with a structured prompt per entitlement:
  risk_score, risk_level, flags, user context, resource sensitivity
- Parse LLM response into: `ai_decision` (approve/revoke/escalate),
  `ai_reasoning` (explanation string), `confidence` (float 0–1)
- Populate `pending_human_review` for all `revoke` decisions
- Write `EntitlementReview` rows to PostgreSQL
- Add tests in `tests/test_decision.py` with prompt/response fixtures
