"""The strategy library, thread search and exports."""
import json

from fastapi import HTTPException, Query
from fastapi.responses import JSONResponse, Response

from balsamic.library import service as library
from balsamic.evolution import ledger, lineage


def _no_store(value, status=200):
    return JSONResponse(value, status_code=status, headers={"Cache-Control": "no-store"})


def install(app, workspace):
    @app.get("/api/v1/library")
    def library_search(campaign_id: str | None = None, problem_id: str | None = None, q: str = "", limit: int = Query(20, ge=1, le=100)):
        if campaign_id:
            workspace.store.get(campaign_id, "campaign")
        return _no_store(library.search(workspace, campaign_id=campaign_id, problem_id=problem_id, q=q, limit=limit))

    @app.get("/api/v1/library/{entry_id}")
    def library_entry(entry_id: str):
        try:
            return _no_store(workspace.store.get(entry_id, "library_entry"))
        except KeyError:
            raise HTTPException(404, "Unknown library entry")

    @app.get("/api/v1/threads/{thread_id}/export")
    def export_thread(thread_id: str):
        from balsamic.threads.service import thread_of, thread_messages, inherited, conversation
        try:
            thread = thread_of(workspace, thread_id)
        except KeyError:
            raise HTTPException(404, "Unknown thread")
        rows = conversation(workspace, thread["campaign_id"])
        own = thread_messages(workspace, thread, rows)
        summaries, inherited_rows = inherited(workspace, thread, rows)
        lines = [f"# {thread['title']}", "", f"Thread {thread['id']} of campaign {thread['campaign_id']}; status {thread['status']}.", ""]
        if summaries:
            lines += ["## Inherited", ""] + [f"### {m.get('role')} · {m.get('created_at')}\n\n{m.get('content', '')}\n" for m in inherited_rows]
        lines += ["## Turns", ""] + [f"### {('You' if m.get('role') == 'user' and m.get('origin') != 'lab_event' else m.get('origin') or m.get('role'))} · {m.get('created_at')}\n\n{m.get('content', '')}\n" for m in own]
        if thread.get("summary"):
            lines += ["## Summary", "", thread["summary"].get("text", ""), f"\n({thread['summary'].get('written_by')})", ""]
        return Response("\n".join(lines), media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="{thread_id}.md"'})

    @app.get("/api/v1/campaigns/{campaign_id}/evolution/export")
    def export_evolution(campaign_id: str):
        workspace.store.get(campaign_id, "campaign")
        rows, cursor = ledger.rows(workspace, campaign_id, with_curves=True)
        nodes, rounds = lineage.layout(rows)
        body = {"campaign_id": campaign_id, "event_cursor": cursor, "rounds": rounds, "nodes": rows, "layout": nodes, "edges": lineage.edges_of(rows),
                "interventions": workspace.store.list("intervention", campaign_id)}
        return Response(json.dumps(body, indent=1, default=str), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{campaign_id}-evolution.json"'})
