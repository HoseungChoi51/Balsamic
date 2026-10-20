"""Panels: the declarative pages agents compose; read resolved, acted on by the researcher."""
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from balsamic.panels import service


class SetValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component_id: str = Field(min_length=1, max_length=64)
    value: Any


def install(app, workspace):
    @app.get("/api/v1/campaigns/{campaign_id}/panels")
    def panels(campaign_id: str, page: str | None = None):
        workspace.store.get(campaign_id, "campaign")
        address = page.lstrip("#") if page else None
        return {"campaign_id": campaign_id, "panels": [service.resolve(workspace, p) for p in service.for_page(workspace, campaign_id, address)]}

    @app.get("/api/v1/panels/{panel_id}")
    def panel(panel_id: str):
        return service.resolve(workspace, workspace.store.get(panel_id, service.KIND))

    @app.post("/api/v1/panels/{panel_id}/set")
    def set_value(panel_id: str, body: SetValue):
        record = workspace.store.get(panel_id, service.KIND)
        try:
            return service.set_value(workspace, record, body.component_id, body.value)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    @app.post("/api/v1/panels/{panel_id}/retire")
    def retire(panel_id: str):
        return service.retire(workspace, panel_id)
