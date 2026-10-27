"""One SSE stream of record changes. Each event names its kind and record, so a page refetches only what it shows."""
import asyncio
import json

from fastapi import Request
from fastapi.responses import StreamingResponse

FRAME_LIMIT = 200


def frame(rows):
    """What a listener needs to decide what to refetch; never the record itself."""
    return [{"id": row["id"], "kind": row["kind"], "record_id": row["data"].get("record_id"), "campaign_id": row["campaign_id"],
             "status": row["data"].get("status"), "revision": row["data"].get("revision")} for row in rows[-FRAME_LIMIT:]]


def install(app, workspace):
    @app.get("/api/v1/events")
    async def events(request: Request, campaign_id: str | None = None, after: int = 0):
        async def stream():
            last = after
            try:
                last = max(last, int(request.headers.get("last-event-id", "0")))
            except ValueError:
                pass
            yield "retry: 2000\n\n"
            heartbeat = 0
            while not await request.is_disconnected():
                rows = workspace.store.events(campaign_id, after=last, limit=500)
                if rows:
                    last = rows[-1]["id"]
                    yield f"id: {last}\nevent: update\ndata: {json.dumps({'last_event_id': last, 'events': frame(rows)})}\n\n"
                else:
                    heartbeat += 1
                    if heartbeat % 15 == 0:
                        yield ": heartbeat\n\n"
                await asyncio.sleep(1)
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
