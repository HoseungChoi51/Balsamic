"""``ui_event`` records: kind, time, campaign, thread, page and a few scalars. Stored once per distinct event."""
from pydantic import Field

from optimization_framework.contracts.base import content_hash
from optimization_framework.contracts.requests import Model
from optimization_framework.storage.sqlite import now

MAX_EVENTS = 64
MAX_LISTED = 500
KINDS = ("page.open", "thread.fork", "thread.switch", "thread.merge", "thread.park", "context.open", "context.pin", "context.exclude",
         "context.forgot_report", "intervention.send", "round.next_action", "monitor.open", "monitor.alert_acted", "chip.open", "trace.open",
         "note.ask", "visual.open", "digest.seen", "search.open")


class UiEvent(Model):
    kind: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_.]*$")
    at: str = Field(min_length=1, max_length=64)
    campaign_id: str | None = Field(default=None, max_length=160)
    thread_id: str | None = Field(default=None, max_length=200)
    page: str | None = Field(default=None, max_length=160)
    session: str | None = Field(default=None, max_length=64)
    data: dict[str, str | int | float | bool | None] = Field(default_factory=dict, max_length=16)


class UiEventBatch(Model):
    workspace_id: str = Field(min_length=1, max_length=200)
    events: list[UiEvent] = Field(min_length=1, max_length=MAX_EVENTS)


def record_batch(workspace, batch):
    entries = []
    for event in batch.events:
        if event.campaign_id is not None:
            workspace.store.get(event.campaign_id, "campaign")
        record = {**event.model_dump(mode="json"), "recorded_at": now()}
        # One record per distinct event; a repeated batch (lost acknowledgement) stores nothing twice.
        record["id"] = "ui_event_" + content_hash({key: record[key] for key in ("kind", "at", "campaign_id", "thread_id", "page", "session", "data")})[:28]
        entries.append(("ui_event", record, None))
    workspace.store.put_many(entries)
    return len(entries)
