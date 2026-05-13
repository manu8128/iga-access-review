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

## Phase 3 — Harvester Agent (Planned)
Implement real DB queries in `HarvesterAgent.run()`:
- Join `Entitlement` → `User` → `Department`, `Manager`, `Resource`
- Filter to `is_active=True` for the campaign scope
- Return fully-populated dicts matching the `scored_entitlements` key contract
  (all fields: `entitlement_id`, `user_name`, `manager_email`, `resource_sensitivity`, etc.)
- Write `Campaign` record to DB with `status=HARVESTING`
- Add `AuditLog` entry for harvest start/complete
- Add corresponding pytest fixture and tests in `tests/test_harvester.py`
