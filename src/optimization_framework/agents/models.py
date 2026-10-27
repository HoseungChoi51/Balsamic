from typing import Literal
from pydantic import Field, model_validator
from optimization_framework.contracts.base import Contract
from optimization_framework.contracts.mandates import MessageMandate


# The campaign lead coordinates the other roles. ("pi" was a misreading of the
# Pi harness as a "principal investigator"; stored records are migrated.)
LEAD = "lead"
# The agents in charge of a page, one of each per campaign. Like the lead they stay for the whole campaign; they take
# requests from the researcher on their page and from the lead, and act on nothing else. The lead's other assistants are
# created for one assignment each.
PAGE_AGENTS = {"discussion_moderator": "hypotheses", "experiment_operator": "experiments", "implementation_lead": "hypotheses/implementations",
               "resource_planner": "monitor/resources"}
STANDING = {LEAD, *PAGE_AGENTS}
# The assistants the moderator asks for views and verdicts in a review round.
DISCUSSION_ROLES = ("literature_specialist", "methodology_specialist", "cross_domain_explorer", "skeptical_domain_analyst",
                    "empirical_assessor", "proposal_reviewer", "results_analyst")
# The implementation service's builder, test designer and validator are no longer roles (roadmap H8): code is built in a coding box
# (agents/development_commission.py). Agents recorded under them keep their records and never run again.
ROLES = (LEAD, "literature_specialist", "methodology_specialist", "cross_domain_explorer",
         "skeptical_domain_analyst", "empirical_assessor", "proposal_reviewer", "results_analyst", *PAGE_AGENTS)
RETIRED_ROLES = frozenset({"implementation_builder", "implementation_test_designer", "implementation_validator"})
# The standing assignment of each page agent.
PAGE_OBJECTIVES = {
    "discussion_moderator": "Run the review of this campaign's proposals when the researcher or the lead agent asks: ask specialists and "
        "reviewers (delegate) for their views and verdicts on the proposals named, have proposals revised where the verdicts ask for it, "
        "set each proposal's status, and report a short synthesis: which proposals stand, which were revised or rejected, and why.",
    "experiment_operator": "Run this campaign's experiments when the researcher or the lead agent asks: design, start, watch, pause, extend "
        "and stop runs within the campaign's allocations, find out why a run failed from its records and files, and report what ran and "
        "what it measured.",
    "implementation_lead": "Build, check and attach optimizer and evaluator implementations when the researcher or the lead agent asks: "
        "coding workspaces (write the ticket, review the delivery) or commissions. Report what was built and checked, and what remains.",
    "resource_planner": "Plan how this campaign uses the machine within the researcher's resource level: estimate what kinds of runs never "
        "measured will use, decide how many of the campaign's runs and of each kind go at once, explain why runs wait or ran out of "
        "memory, and report the plan and its reasons. Start no runs and stop none.",
}


THINKING = Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"]


class ModelChoice(Contract):
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    effort: THINKING | None = None


# The lead agent's standing assignment. Starting the team starts no work: what the campaign does next is
# the researcher's to ask for, one request at a time or several stages in one.
STANDING_OBJECTIVE = "Carry out what the researcher of this campaign asks for, report the result, and wait for the next request."
# The default of earlier versions, which told the lead to work through the campaign unasked. Saved records are migrated.
FORMER_OBJECTIVE = "Continue the campaign from its saved evidence and unfinished requests."
# Every turn the platform starts without a researcher's message begins with this line.
NOTICE = "[Platform notice. This is not a request from the researcher.]\n"


class Activate(Contract):
    objective: str = Field(default=STANDING_OBJECTIVE, min_length=1, max_length=20000)
    max_subagents: int = Field(default=4, ge=1, le=8)
    delegated: bool = True
    # Default model for the campaign's agents; it also fixes the campaign's model family.
    model: ModelChoice | None = None


class Configure(Contract):
    """Dev mode: change the model or thinking level of one agent, or the campaign default.

    follow_tier releases an agent pinned to its own model back to its role's tier.
    """
    agent_id: str | None = None
    model: ModelChoice | None = None
    follow_tier: bool = False

    @model_validator(mode="after")
    def one_change(self):
        if (self.model is None) != self.follow_tier:
            raise ValueError("Choose a model, or ask the agent to follow its tier")
        return self


class Message(Contract):
    agent_id: str | None = None
    # The agent in charge of a page, by its role: created the first time it is written to.
    page_agent: Literal["discussion_moderator", "experiment_operator", "implementation_lead", "resource_planner"] | None = None
    message: str = Field(min_length=1, max_length=50000)
    mode: Literal["steer", "follow_up"] = "steer"
    question_id: str | None = None
    # The conversation thread the message belongs to (its campaign's main thread when absent).
    thread_id: str | None = None
    parent_message_id: str | None = None
    edit_of_message_id: str | None = None
    # The mandate the researcher grants with this message, for the request it opens (R7, the dial beside the chat's send button).
    mandate: MessageMandate | None = None

    @model_validator(mode="after")
    def one_recipient(self):
        if self.agent_id and self.page_agent:
            raise ValueError("Name the agent or the page agent, not both")
        return self


class QuestionDismiss(Contract):
    """The researcher sets an agent's question aside without answering it."""
    question_id: str = Field(min_length=1, max_length=200)


class UiRespond(Contract):
    """The researcher's answer to an extension's dialog: a choice, yes or no, a text; or cancelled. It goes back to the waiting
    extension, not into a turn."""
    question_id: str = Field(min_length=1, max_length=200)
    value: str | bool | None = None
    cancelled: bool = False

    @model_validator(mode="after")
    def answer_or_cancel(self):
        if self.cancelled == (self.value is not None):
            raise ValueError("Give a value or cancel the dialog, not both")
        if isinstance(self.value, str) and len(self.value) > 20000:
            raise ValueError("An answer is at most 20,000 characters")
        return self


class Control(Contract):
    agent_id: str | None = None
    action: Literal["pause", "resume", "stop"]
    expected_control_revision: int = Field(ge=0)


class Rollback(Contract):
    reason: str = Field(min_length=1, max_length=5000)
