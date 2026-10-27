"""The problem note: read it, and ask the cheap tiers without the bus."""
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from balsamic.notes import service as notes


def _no_store(value, status=200):
    return JSONResponse(value, status_code=status, headers={"Cache-Control": "no-store"})


def install(app, workspace):
    @app.get("/api/v1/campaigns/{campaign_id}/problem-note")
    def campaign_note(campaign_id: str):
        workspace.store.get(campaign_id, "campaign")
        note = notes.ensure_note(workspace, campaign_id)
        return _no_store(notes.view(workspace, note["id"]))

    @app.get("/api/v1/problem-notes/{note_id}")
    def problem_note(note_id: str, revision: int | None = None):
        try:
            return _no_store(notes.view(workspace, note_id, revision=revision))
        except KeyError:
            raise HTTPException(404, "Unknown note or revision")

    @app.post("/api/v1/problem-notes/{note_id}/ask")
    def ask(note_id: str, body: notes.AskInput):
        if body.note_id != note_id:
            raise HTTPException(422, "The note in the body differs from the address")
        try:
            record = notes.ask(workspace, body)
        except KeyError:
            raise HTTPException(404, "Unknown note or revision")
        return _no_store(record)

    @app.get("/api/v1/problem-notes/{note_id}/preview")
    def preview(note_id: str, revision: int | None = None):
        note = workspace.store.get(note_id, "problem_note")
        current = notes.revision_of(workspace, note_id, revision or note["current_revision"])
        return _no_store({"markdown": notes.markdown(current)})
