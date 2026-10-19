"""Local UI telemetry: which controls researchers use, never what they wrote. Gate signals for the plan's milestones."""
from fastapi import HTTPException, Query
from fastapi.responses import JSONResponse

from balsamic.telemetry.events import UiEventBatch, MAX_LISTED, record_batch
from balsamic.telemetry.signals import gate


def _no_store(value, status=200):
    return JSONResponse(value, status_code=status, headers={"Cache-Control": "no-store"})


def install(app, workspace):
    @app.post("/api/v1/ui-events", status_code=202)
    def record_ui_events(batch: UiEventBatch):
        if batch.workspace_id != workspace.store.identity():
            raise HTTPException(404, "Unknown workspace")
        try:
            return _no_store({"recorded": record_batch(workspace, batch)}, 202)
        except KeyError:
            raise HTTPException(404, "Unknown campaign")

    @app.get("/api/v1/ui-events")
    def list_ui_events(campaign_id: str | None = None, limit: int = Query(200, ge=1, le=MAX_LISTED)):
        rows = workspace.store.list("ui_event", campaign_id)
        return _no_store({"events": rows[-limit:], "total": len(rows)})

    @app.get("/api/v1/ui-events/gate")
    def ui_gate(campaign_id: str | None = None, milestone: str = Query("M1", pattern=r"^M[1-4]$")):
        return _no_store(gate(workspace, campaign_id, milestone))
