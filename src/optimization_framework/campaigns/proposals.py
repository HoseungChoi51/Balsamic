"""Explicit exploration intent and independent conceptual review of exact proposals.

Text review grants eligibility for small experiments, never evidence of performance.
Implementation correctness and numerical resource checks remain separate gates.
"""
from typing import Literal

from pydantic import Field

from optimization_framework.contracts.base import Contract
from optimization_framework.contracts.base import content_hash


def hypothesis_revision(hypothesis):
    return content_hash({key: hypothesis.get(key) for key in ("id", "title", "mechanism", "rationale", "parent_ids", "algorithm_config", "candidate_id")})


class ProposalReview(Contract):
    candidate_id: str
    verdict: Literal["test", "revise", "reject"]
    rationale: str = Field(min_length=1, max_length=8000)
    mechanism_checks: list[str] = Field(min_length=1, max_length=20)
    conflicts_and_risks: list[str] = Field(default_factory=list, max_length=20)
    required_changes: list[str] = Field(default_factory=list, max_length=20,
        description="Changes to the proposed mechanism/specification. Missing code or funding belongs in implementation_followup, not here.")
    implementation_followup: list[str] = Field(default_factory=list, max_length=20,
        description="Separate implementation/readiness concerns; these do not determine conceptual plausibility.")
    suggested_tests: list[str] = Field(min_length=1, max_length=20)


def readiness(store, hypothesis):
    if not hypothesis or not hypothesis.get("requires_concept_review"):
        return {"state": "not_required", "eligible": True, "review_ids": []}
    reviews = [row for row in store.list("agent_artifact", hypothesis["campaign_id"])
        if row.get("kind") == "proposal_review" and row["content"].get("hypothesis_id") == hypothesis["id"]
        and row["content"].get("hypothesis_hash") == hypothesis_revision(hypothesis)]
    if not reviews:
        return {"state": "pending", "eligible": False, "review_ids": [],
                "reason": "An independent conceptual review is required before testing this proposal."}
    # A reviewer's later review of this revision replaces its own earlier one; another reviewer's objection still stands.
    reviews = list({row.get("agent_id"): row for row in sorted(reviews, key=lambda row: row.get("created_at", ""))}.values())
    objections = [row for row in reviews if row["content"]["verdict"] != "test"]
    return {"state": "revision_required" if objections else "testable", "eligible": not objections,
            "review_ids": [row["id"] for row in reviews],
            "reason": "An independent reviewer requested changes or rejected this revision. Create a linked revision and review it again."
                if objections else "Independently judged plausible enough for quick tests; effectiveness remains unmeasured."}
