"""
scripts/evaluate_decisions.py
------------------------------
Evaluation script — measures LLM decision accuracy vs ground truth.

Runs a campaign against the seed data and compares AI decisions to the
known-correct answers based on IGA access review policy.

Usage:
    python scripts/evaluate_decisions.py
    # OR (from project root)
    .venv/bin/python -m scripts.evaluate_decisions

REQUIRES:
    - Docker PostgreSQL running with seed data loaded:
          docker-compose up -d db && python -m db.seed
    - Valid LLM config in .env (e.g. LLM_PROVIDER=ollama, LLM_MODEL=llama3.1:8b)
"""
import sys
from pathlib import Path

# Add project root to sys.path so config/orchestrator imports work
sys.path.append(str(Path(__file__).resolve().parent.parent))

import uuid

from orchestrator.graph import resume_campaign, run_campaign

# --------------------------------------------------------------------------- #
# Ground truth                                                                 #
# --------------------------------------------------------------------------- #

GROUND_TRUTH: dict[str, str] = {
    # format: "user_name|resource_name": "expected_decision"
    "Bob Kumar|SAP Finance Admin":      "revoke",    # stale 180d + junior Admin
    "Bob Kumar|HRIS Full Access":       "revoke",    # never used critical resource
    "Dan Smith|AWS Production Admin":   "revoke",    # stale 200d + junior Admin
    "Frank Lee|SAP Finance Admin":      "revoke",    # SoD violation
    "Frank Lee|AWS Production Admin":   "escalate",  # SoD but recently used
    "Alice Wong|SAP Finance Admin":     "approve",   # used yesterday, appropriate role
    "Alice Wong|SAP Finance Read":      "approve",   # used yesterday, low risk
    "Carol Davis|AWS Dev Access":       "approve",   # used daily, appropriate
    "Carol Davis|GitHub Repo Read":     "approve",   # used regularly, low risk
    "Carol Davis|GitHub Org Admin":     "approve",   # staff engineer, acceptable
    "Dan Smith|AWS Dev Access":         "approve",   # used recently, appropriate
    "Eve Johnson|HRIS Full Access":     "approve",   # HR role, used daily
    "Eve Johnson|Payroll View":         "approve",   # HR role, used recently
}


# --------------------------------------------------------------------------- #
# Evaluation logic                                                             #
# --------------------------------------------------------------------------- #

def run_evaluation() -> dict:
    """Run a campaign and measure decision accuracy vs ground truth.

    Returns:
        Dict with keys: campaign_id, accuracy, correct, incorrect, total,
        precision_revoke, recall_revoke, mismatches
    """
    campaign_id = f"eval-{uuid.uuid4().hex[:8]}"
    result = run_campaign(campaign_id, "Evaluation Campaign")

    # If graph paused at HITL, auto-approve all pending in eval mode.
    # We want to capture the AI decisions without manual intervention.
    if result.get("status") == "deciding":
        pending = result.get("pending_human_review", [])
        auto_decisions = [
            {
                "entitlement_id": p["entitlement_id"],
                "human_decision": "approve",
                "human_reviewer": "eval_script",
            }
            for p in pending
        ]
        result = resume_campaign(campaign_id, auto_decisions)

    decisions = result.get("decisions", [])
    correct = 0
    incorrect = 0
    mismatches: list[dict] = []

    for d in decisions:
        key = f"{d['user_name']}|{d['resource_name']}"
        expected = GROUND_TRUTH.get(key)
        actual = d["ai_decision"]
        if expected is None:
            continue  # entitlement not in ground truth — skip
        if actual == expected:
            correct += 1
        else:
            incorrect += 1
            mismatches.append({
                "key": key,
                "expected": expected,
                "actual": actual,
                "risk_score": d["risk_score"],
                "risk_level": d["risk_level"],
                "flags": d["flags"],
                "reasoning": d["ai_reasoning"],
            })

    total = correct + incorrect
    accuracy = correct / total if total > 0 else 0.0

    # Precision and recall for revoke decisions
    true_positives = sum(
        1 for d in decisions
        if f"{d['user_name']}|{d['resource_name']}" in GROUND_TRUTH
        and d["ai_decision"] == "revoke"
        and GROUND_TRUTH[f"{d['user_name']}|{d['resource_name']}"] == "revoke"
    )
    predicted_revokes = sum(1 for d in decisions if d["ai_decision"] == "revoke")
    actual_revokes = sum(1 for v in GROUND_TRUTH.values() if v == "revoke")

    precision = true_positives / predicted_revokes if predicted_revokes > 0 else 0.0
    recall = true_positives / actual_revokes if actual_revokes > 0 else 0.0

    return {
        "campaign_id": campaign_id,
        "accuracy": round(accuracy, 3),
        "correct": correct,
        "incorrect": incorrect,
        "total": total,
        "precision_revoke": round(precision, 3),
        "recall_revoke": round(recall, 3),
        "mismatches": mismatches,
    }


if __name__ == "__main__":
    import json
    results = run_evaluation()
    print(json.dumps(results, indent=2))
    print(f"\nAccuracy:          {results['accuracy']:.1%}")
    print(f"Revoke Precision:  {results['precision_revoke']:.1%}")
    print(f"Revoke Recall:     {results['recall_revoke']:.1%}")
    print(f"Mismatches:        {results['incorrect']}/{results['total']}")
