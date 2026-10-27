"""HTTP routes for problem charters: start, read, edit, answer, ask, decide, confirm and fork."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from . import charter as mechanics


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FromExample(Body):
    example_id: str = Field(min_length=1, max_length=200)


class FromEvaluator(Body):
    problem_id: str = Field(min_length=1, max_length=200)


class ForCampaign(Body):
    campaign_id: str = Field(min_length=1, max_length=200)


class Changes(Body):
    changes: list[dict[str, Any]] = Field(default_factory=list, max_length=200)


class Edit(Body):
    expected_revision: int = Field(ge=1)
    changes: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    charter: dict[str, Any] | None = None
    rationale: str = Field(default="", max_length=2000)


class Accept(Body):
    expected_revision: int = Field(ge=1)
    names: list[str] | None = None


class Waive(Body):
    expected_revision: int = Field(ge=1)
    key: str = Field(min_length=1, max_length=300)
    reason: str = Field(min_length=1, max_length=2000)


class Answer(Body):
    expected_revision: int = Field(ge=1)
    question_id: str = Field(min_length=1, max_length=64)
    answer: str = Field(min_length=1, max_length=5000)


class Request(Body):
    text: str = Field(min_length=1, max_length=5000)


class SendAnswers(Body):
    expected_revision: int = Field(ge=1)


class Decision(Body):
    option: int | None = Field(default=None, ge=0, le=2)


class Confirm(Body):
    expected_revision: int = Field(ge=1)


class ForkBody(Body):
    changes: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    revision: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, max_length=200)


class TextCheck(Body):
    text: str = Field(default="", max_length=20000)


def install(app, workspace):
    charters = workspace.charters

    @app.get("/api/v1/problem-charters")
    def problem_charters():
        return {"charters": charters.list()}

    @app.post("/api/v1/problem-charters/from-example")
    def from_example(body: FromExample):
        return charters.view(charters.from_example(body.example_id)["id"])

    @app.post("/api/v1/problem-charters/from-evaluator")
    def from_evaluator(body: FromEvaluator):
        return charters.view(charters.from_evaluator(body.problem_id)["id"])

    @app.post("/api/v1/problem-charters/for-campaign")
    def for_campaign(body: ForCampaign):
        return charters.view(charters.for_campaign(body.campaign_id)["id"])

    @app.get("/api/v1/problem-charters/{charter_id}")
    def problem_charter(charter_id: str):
        return charters.view(charter_id)

    @app.delete("/api/v1/problem-charters/{charter_id}")
    def remove_charter(charter_id: str):
        return charters.remove(charter_id)

    @app.get("/api/v1/problem-charters/{charter_id}/revisions/{number}")
    def charter_revision(charter_id: str, number: int):
        return charters.revision(charter_id, number)

    @app.post("/api/v1/problem-charters/{charter_id}/preview")
    def preview(charter_id: str, body: Changes):
        return charters.preview(charter_id, body.changes)

    @app.post("/api/v1/problem-charters/{charter_id}/edit")
    def edit(charter_id: str, body: Edit):
        charters.edit(charter_id, body.changes, expected_revision=body.expected_revision, rationale=body.rationale, charter=body.charter)
        return charters.view(charter_id)

    @app.post("/api/v1/problem-charters/{charter_id}/accept-assumptions")
    def accept(charter_id: str, body: Accept):
        charters.accept_assumptions(charter_id, body.names, expected_revision=body.expected_revision)
        return charters.view(charter_id)

    @app.post("/api/v1/problem-charters/{charter_id}/waive")
    def waive(charter_id: str, body: Waive):
        charters.waive(charter_id, body.key, body.reason, expected_revision=body.expected_revision)
        return charters.view(charter_id)

    @app.post("/api/v1/problem-charters/{charter_id}/answers")
    def answer(charter_id: str, body: Answer):
        charters.answer(charter_id, body.question_id, body.answer, expected_revision=body.expected_revision)
        return charters.view(charter_id)

    @app.post("/api/v1/problem-charters/{charter_id}/send-answers")
    def send_answers(charter_id: str, body: SendAnswers):
        """The round as it stands: unanswered questions go to the formulator as decisions it makes and records."""
        charters.send_answers(charter_id, expected_revision=body.expected_revision)
        return charters.view(charter_id)

    @app.post("/api/v1/problem-charters/{charter_id}/requests")
    def request(charter_id: str, body: Request):
        charters.request(charter_id, body.text)
        return charters.view(charter_id)

    @app.post("/api/v1/problem-charter-proposals/{proposal_id}/decision")
    def decide(proposal_id: str, body: Decision):
        record = charters.decide(proposal_id, body.option)
        return charters.view(record["id"])

    @app.post("/api/v1/problem-charters/{charter_id}/confirm")
    def confirm(charter_id: str, body: Confirm):
        return charters.confirm(charter_id, expected_revision=body.expected_revision)

    @app.post("/api/v1/problem-charters/{charter_id}/fork")
    def fork(charter_id: str, body: ForkBody):
        return charters.view(charters.fork(charter_id, body.changes, revision=body.revision, title=body.title)["id"])

    @app.post("/api/v1/problem-charters/{charter_id}/text-check")
    def text_check(charter_id: str, body: TextCheck):
        """Numbers in a text (such as the research question) that belong to the charter's quantities."""
        record = charters.get(charter_id)
        parsed = mechanics.parse(record["charter"])
        values = mechanics.resolve(parsed)["values"]
        return {"findings": mechanics.literal_findings(body.text, "research question", parsed, values)}
