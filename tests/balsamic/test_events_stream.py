import asyncio
import json

from balsamic.api.events import frame


def test_event_frames_name_kind_record_status_and_revision(client, campaign, workspace):
    rows = workspace.store.events("demo")
    kinds = {row["kind"] for row in rows}
    assert {"campaign.created", "thread.created", "study.created"} <= kinds
    thread_event = next(item for item in frame(rows) if item["kind"] == "thread.created")
    assert thread_event == {"id": thread_event["id"], "kind": "thread.created", "record_id": "thread_main_demo", "campaign_id": "demo", "status": "active", "revision": None}
    assert all(set(item) == {"id", "kind", "record_id", "campaign_id", "status", "revision"} for item in frame(rows))


def test_the_stream_sends_one_frame_per_batch_and_keeps_the_cursor(app, client, campaign, workspace):
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/v1/events")

    class Request:
        headers = {}
        def __init__(self): self.polls = 0
        async def is_disconnected(self):
            self.polls += 1
            return self.polls > 2

    async def collect():
        response = await endpoint(Request(), campaign_id="demo", after=0)
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        return chunks
    chunks = asyncio.run(collect())
    assert chunks[0] == "retry: 2000\n\n"
    data = [json.loads(chunk.split("data: ", 1)[1].strip()) for chunk in chunks if chunk.startswith("id: ")]
    assert len(data) == 1
    assert data[0]["last_event_id"] == workspace.store.events("demo")[-1]["id"]
    assert any(event["kind"] == "campaign.created" and event["record_id"] == "demo" for event in data[0]["events"])
