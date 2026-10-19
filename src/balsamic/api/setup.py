"""Starting a campaign as a conversation."""
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from balsamic.setup import service as setup


def _no_store(value, status=200):
    return JSONResponse(value, status_code=status, headers={"Cache-Control": "no-store"})


def install(app, workspace):
    @app.post("/api/v1/setup", status_code=201)
    def start():
        return _no_store(setup.start(workspace), 201)

    @app.get("/api/v1/setup/{setup_id}")
    def read(setup_id: str):
        try:
            return _no_store(workspace.store.get(setup_id, "campaign_setup"))
        except KeyError:
            raise HTTPException(404, "Unknown setup")

    @app.post("/api/v1/setup/{setup_id}/answer")
    def answer(setup_id: str, body: setup.AnswerInput):
        try:
            return _no_store(setup.answer(workspace, setup_id, body))
        except KeyError:
            raise HTTPException(404, "Unknown setup")

    @app.post("/api/v1/setup/{setup_id}/edit")
    def edit(setup_id: str, body: setup.EditInput):
        try:
            record = workspace.store.get(setup_id, "campaign_setup")
        except KeyError:
            raise HTTPException(404, "Unknown setup")
        if record["status"] == "created":
            raise ValueError("This setup already created its campaign")
        with workspace.lock:
            record["transcript"].append({"role": "user", "text": "Change the " + body.field, "field": "ready", "at": setup.now()})
            return _no_store(setup._ask(workspace, record, body.field, "Sure. "))

    @app.post("/api/v1/setup/{setup_id}/create")
    def create(setup_id: str):
        try:
            return _no_store(setup.create(workspace, setup_id))
        except KeyError:
            raise HTTPException(404, "Unknown setup")
