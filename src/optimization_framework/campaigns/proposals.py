"""Explicit exploration intent and independent conceptual review of exact proposals.

Text review grants eligibility for small experiments, never evidence of performance.
Implementation correctness and numerical resource checks remain separate gates.
A proposal the researcher asked for (decision 7) or approved in a compute plan needs no review: one that exists is advisory.
"""
from typing import Literal

from pydantic import Field, model_validator

from optimization_framework.contracts.base import Contract
from optimization_framework.contracts.base import content_hash
from optimization_framework.storage.sqlite import now


def revision_fields(hypothesis):
    """The fields of the exact revision a review judges. A bound proposal counts the configuration its first binding replaced,
    so binding it to an installed method does not void its review."""
    fields = {key: hypothesis.get(key) for key in ("id", "title", "mechanism", "rationale", "parent_ids", "algorithm_config", "candidate_id")}
    if "pre_binding_config" in hypothesis:
        fields["algorithm_config"] = hypothesis["pre_binding_config"]
    return fields


def hypothesis_revision(hypothesis):
    """The hash of the exact revision a review judges (revision_fields)."""
    return content_hash(revision_fields(hypothesis))


class Review(Contract):
    """A reviewer's verdict on one revision. A one-shot review call returns exactly this (roadmap T1): the backend adds the
    hypothesis and the revision's hash, so a model never names or pins them."""
    verdict: Literal["test", "revise", "reject"]
    rationale: str = Field(min_length=1, max_length=8000)
    mechanism_checks: list[str] = Field(min_length=1, max_length=20)
    conflicts_and_risks: list[str] = Field(default_factory=list, max_length=20)
    required_changes: list[str] = Field(default_factory=list, max_length=20,
        description="Changes to the proposed mechanism/specification. Missing code or funding belongs in implementation_followup, not here.")
    implementation_followup: list[str] = Field(default_factory=list, max_length=20,
        description="Separate implementation/readiness concerns; these do not determine conceptual plausibility.")
    suggested_tests: list[str] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def settled_before_test(self):
        if self.verdict == "test" and self.required_changes:
            raise ValueError("Required mechanism changes must be resolved before a test verdict")
        return self


class ProposalReview(Review):
    candidate_id: str


def record_review(store, hypothesis, content, *, artifact_id, agent_id, run_id):
    """Save a verdict on a revision as proposal_review always has: an immutable agent_artifact of kind proposal_review pinning
    the hash (content holds hypothesis_id and hypothesis_hash), and the verdict appended to the hypothesis's reviews."""
    if content["verdict"] == "test" and content.get("required_changes"):
        raise ValueError("Required mechanism changes must be resolved before a test verdict")
    artifact = store.put_immutable("agent_artifact", {"id": artifact_id, "campaign_id": hypothesis["campaign_id"],
        "agent_id": agent_id, "run_id": run_id, "kind": "proposal_review", "content": content,
        "created_at": now()}, "hypothesis.concept_reviewed")
    hypothesis = store.get(hypothesis["id"], "hypothesis")
    hypothesis.setdefault("reviews", []).append({"id": artifact["id"], "author": "proposal_reviewer", "kind": "conceptual",
        "verdict": content["verdict"], "text": content["rationale"], "created_at": now()})
    store.put("hypothesis", hypothesis)
    return artifact


def researcher_request(workspace, origin):
    """The researcher's message a lead turn answers, as {thread_id, message_id}; None for an autopilot turn, a notice turn
    whose request no researcher message opened, or a command from any other agent (decision 7)."""
    origin = origin if isinstance(origin, dict) else origin.model_dump() if origin is not None else {}
    run = _record(workspace, origin.get("run_id"), "agent_run")
    from optimization_framework.agents.models import LEAD
    if run is None or (_record(workspace, run.get("agent_id"), "agent_session") or {}).get("role") != LEAD:
        return None
    root = workspace.pi.request_root(run)
    # A notice turn continues the request of the turn its root names; any other turn is its own request.
    asked = _record(workspace, (root or {}).get("run_id"), "agent_run") if (run.get("origin") or {}).get("root") else run
    started = (asked or {}).get("origin") or {}
    if asked is None or asked.get("autopilot") or started.get("actor") != "researcher" or not started.get("message_id"):
        return None
    return {"thread_id": started["thread_id"], "message_id": started["message_id"]}


def approve(workspace, consent):
    """The researcher's go-ahead of a compute plan approves each proposal it names, unless an earlier one did."""
    for identity in consent.get("hypothesis_ids") or []:
        hypothesis = _record(workspace, identity, "hypothesis")
        if hypothesis is not None and not hypothesis.get("approved_by"):
            hypothesis["approved_by"] = {"decision_id": consent["decision_id"], "consent_id": consent["id"]}
            workspace.store.put("hypothesis", hypothesis)


def _record(workspace, identity, kind):
    try:
        return workspace.store.get(identity, kind) if isinstance(identity, str) else None
    except KeyError:
        return None


def readiness(store, hypothesis):
    if not hypothesis or not hypothesis.get("requires_concept_review"):
        return {"state": "not_required", "eligible": True, "review_ids": []}
    reviews = [row for row in store.list("agent_artifact", hypothesis["campaign_id"])
        if row.get("kind") == "proposal_review" and row["content"].get("hypothesis_id") == hypothesis["id"]
        and row["content"].get("hypothesis_hash") == hypothesis_revision(hypothesis)]
    # A reviewer's later review of this revision replaces its own earlier one; another reviewer's objection still stands.
    reviews = list({row.get("agent_id"): row for row in sorted(reviews, key=lambda row: row.get("created_at", ""))}.values())
    objections = [row for row in reviews if row["content"]["verdict"] != "test"]
    if hypothesis.get("requested_by") or hypothesis.get("approved_by"):
        # The researcher's request or go-ahead stands in for the review: one that exists is shown, and an objection does not block.
        return {"state": "not_required", "eligible": True, "review_ids": [row["id"] for row in reviews],
                "advisory": [row["id"] for row in objections],
                **{key: hypothesis[key] for key in ("requested_by", "approved_by") if hypothesis.get(key)},
                "reason": "Asked for by the researcher." if hypothesis.get("requested_by") else "In a plan the researcher approved."}
    if not reviews:
        return {"state": "pending", "eligible": False, "review_ids": [],
                "reason": "An independent conceptual review is required before testing this proposal."}
    return {"state": "revision_required" if objections else "testable", "eligible": not objections,
            "review_ids": [row["id"] for row in reviews],
            "reason": "An independent reviewer requested changes or rejected this revision. Create a linked revision and review it again."
                if objections else "Independently judged plausible enough for quick tests; effectiveness remains unmeasured."}
