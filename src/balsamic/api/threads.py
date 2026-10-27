"""Threads, their messages, and the live stream of the lead's turn in one of them."""
import asyncio
import json

from fastapi import HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from balsamic.threads import service as threads
from balsamic.threads.stream import agent_state, live_entry, stream_events

SNAPSHOT_MESSAGES = 40
STREAM_INTERVAL = 1.0


def _no_store(value, status=200):
    return JSONResponse(value, status_code=status, headers={"Cache-Control": "no-store"})


def scoped(workspace, campaign_id, after, body):
    """A read that answers unchanged when the campaign has no event newer than the caller's cursor."""
    cursor = threads.event_cursor(workspace, campaign_id)
    if after and after >= cursor:
        return _no_store({"campaign_id": campaign_id, "event_cursor": cursor, "unchanged": True})
    return _no_store({"campaign_id": campaign_id, "event_cursor": cursor, "unchanged": False, **body()})


def install(app, workspace):
    @app.get("/api/v1/campaigns/{campaign_id}/threads")
    def list_threads(campaign_id: str, after: int = Query(0, ge=0), q: str = ""):
        try:
            workspace.store.get(campaign_id, "campaign")
            if q.strip():
                return _no_store(threads.search(workspace, campaign_id, q))
            return scoped(workspace, campaign_id, after, lambda: threads.threads(workspace, campaign_id))
        except KeyError:
            raise HTTPException(404, "Unknown campaign")

    @app.get("/api/v1/threads/{thread_id}")
    def thread(thread_id: str):
        try:
            return _no_store(threads.thread_of(workspace, thread_id))
        except KeyError:
            raise HTTPException(404, "Unknown thread")

    @app.get("/api/v1/threads/{thread_id}/messages")
    def thread_messages(thread_id: str, after: int = Query(0, ge=0), before: str | None = None, limit: int = Query(threads.MESSAGE_LIMIT, ge=1, le=1000)):
        try:
            thread = threads.thread_of(workspace, thread_id)
        except KeyError:
            raise HTTPException(404, "Unknown thread")
        return scoped(workspace, thread["campaign_id"], after, lambda: threads.messages(workspace, thread_id, limit=limit, before=before))

    @app.get("/api/v1/threads/{thread_id}/context")
    def thread_context(thread_id: str):
        from balsamic.threads.context import context_view
        try:
            return _no_store(context_view(workspace, thread_id))
        except KeyError:
            raise HTTPException(404, "Unknown thread")

    @app.get("/api/v1/threads/{thread_id}/stream")
    async def thread_stream(thread_id: str, request: Request):
        try:
            thread = threads.thread_of(workspace, thread_id)
        except KeyError:
            raise HTTPException(404, "Unknown thread")
        campaign_id = thread["campaign_id"]

        def observe():
            lead = threads.lead_agent(workspace, campaign_id)
            rows = threads.thread_messages(workspace, threads.thread_of(workspace, thread_id))[-SNAPSHOT_MESSAGES:]
            if lead is None:
                return {"threadId": thread_id, "agentId": None, "status": "absent", "requestOpen": False}, None, rows
            state = agent_state(workspace, campaign_id, lead["id"], thread_id)
            entry = live_entry(workspace, campaign_id, lead["id"]) if state["status"] in {"queued", "running"} else None
            # Only the run that this thread asked for is this thread's turn.
            if entry and entry.get("run_id"):
                try:
                    run = workspace.store.get(entry["run_id"], "agent_run")
                    if (run.get("origin") or {}).get("thread_id", threads.main_thread_id(campaign_id)) != thread_id:
                        entry = None
                except KeyError:
                    pass
            return state, entry, rows

        async def lines():
            previous = {}
            yield "retry: 2000\n\n"
            quiet = 0
            while not await request.is_disconnected():
                try:
                    state, entry, rows = await run_in_threadpool(observe)
                except KeyError:
                    yield "event: gone\ndata: {}\n\n"
                    return
                events, previous = stream_events(previous, state, entry, rows)
                for event in events:
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                quiet = 0 if events else quiet + 1
                if quiet and quiet % 15 == 0:
                    yield ": keepalive\n\n"
                await asyncio.sleep(STREAM_INTERVAL)

        return StreamingResponse(lines(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
