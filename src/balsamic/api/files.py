"""Files: assets, bundles, implementations, reports and the agent log (the last two keep their own routers)."""
import asyncio

from fastapi import Query, Request
from fastapi.responses import FileResponse

from balsamic.api.threads import scoped


def install(app, workspace):
    from optimization_framework.api.agent_log import install as install_agent_log
    install_agent_log(app, workspace)
    from optimization_framework.api.reports import install as install_reports
    install_reports(app, workspace)

    @app.get("/api/v1/campaigns/{campaign_id}/files")
    def files(campaign_id: str, after: int = Query(0, ge=0)):
        workspace.store.get(campaign_id, "campaign")

        def body():
            keys = ("id", "campaign_id", "title", "kind", "producer_id", "applicability", "cost_provenance", "exposure_status", "availability", "created_at")
            assets = [{**{key: asset.get(key) for key in keys}, "availability": workspace.assets.availability(asset)["status"]}
                      for asset in workspace.assets.visible(campaign_id)]
            return {"assets": assets, "findings": [row for row in workspace.store.list("manager_note", campaign_id) if row.get("kind") in {"finding", "counterevidence"}],
                    "reports": app.state.reports.list(campaign_id) if hasattr(app.state.reports, "list") else [],
                    "report_jobs": workspace.store.list("report_writer_job", campaign_id),
                    "sources": workspace.store.list("source", campaign_id), "artifacts": workspace.store.list("agent_artifact", campaign_id)}
        return scoped(workspace, campaign_id, after, body)

    @app.get("/api/v1/assets")
    def asset_catalog(campaign_id: str | None = None):
        keys = ("id", "campaign_id", "title", "kind", "producer_id", "applicability", "cost_provenance", "exposure_status", "availability", "created_at")
        return [{**{key: asset.get(key) for key in keys}, "availability": workspace.assets.availability(asset)["status"]}
                for asset in workspace.assets.visible(campaign_id)]

    @app.get("/api/v1/assets/{asset_id}")
    def asset_detail(asset_id: str):
        from optimization_framework.storage.history import producers
        from optimization_framework.assets.accounting import sources
        from optimization_framework.assets.service_costs import AXES
        asset = workspace.store.get(asset_id, "asset")
        return {"asset": asset, "full_attributed_cost": workspace.assets.attributed_costs([asset_id], axes=AXES),
                "local_availability": workspace.assets.availability(asset), "historical_producers": producers(workspace.store, asset),
                "accounting_sources": sources(workspace.assets, asset_id),
                "decisions": [item for item in workspace.store.list("reuse_decision") if item["asset_id"] == asset_id]}

    @app.post("/api/v1/bundle-uploads")
    async def upload_bundle(request: Request):
        import tempfile
        from optimization_framework.storage.bundles import MAX_BUNDLE_BYTES
        size = 0
        with tempfile.TemporaryFile() as stream:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_BUNDLE_BYTES:
                    raise ValueError("Bundle exceeds the supported byte allowance")
                stream.write(chunk)
            stream.seek(0)
            return await asyncio.to_thread(workspace.bundles.upload, stream)

    @app.get("/api/v1/bundles/operations")
    def bundle_operations(campaign_id: str):
        workspace.store.get(campaign_id, "campaign")
        return workspace.store.list("bundle_operation", campaign_id)

    @app.get("/api/v1/bundles/operations/{operation_id}")
    def bundle_operation(operation_id: str):
        return workspace.store.get(operation_id, "bundle_operation")

    @app.get("/api/v1/bundles/operations/{operation_id}/download")
    def download_bundle(operation_id: str):
        from optimization_framework.contracts.experiments import ArtifactReference
        operation = workspace.store.get(operation_id, "bundle_operation")
        if operation["action"] != "export" or operation["status"] != "completed":
            raise ValueError("Bundle export is not complete")
        reference = ArtifactReference(**operation["archive"])
        workspace.assets.artifacts.verify(reference)
        return FileResponse(workspace.assets.artifacts.resolve(reference), filename=operation["bundle_digest"] + ".zip",
                            media_type="application/vnd.optimization.evidence+zip")

    @app.get("/api/v1/implementations")
    def implementation_catalog(campaign_id: str | None = None, hypothesis_id: str | None = None, task_id: str | None = None):
        catalog = workspace.implementations.catalog(refresh=True)
        if campaign_id:
            from optimization_framework.implementations.reuse import assess
            from optimization_framework.implementations.references import catalog as reference_catalog
            catalog["references"] = reference_catalog(workspace.store, campaign_id)
            catalog["candidates"] = {version["id"]: assess(workspace.implementations, campaign_id, version, hypothesis_id=hypothesis_id, task_id=task_id)
                                     for version in catalog["versions"]}
        return catalog

    @app.get("/api/v1/campaigns/{campaign_id}/methods")
    def campaign_methods(campaign_id: str):
        """Which methods the campaign can run, and why the others cannot (campaigns/method_catalog.py)."""
        from optimization_framework.campaigns.method_catalog import catalog
        workspace.store.get(campaign_id, "campaign")
        return catalog(workspace, campaign_id)

    @app.get("/api/v1/implementation-references/{reference_id}")
    def implementation_reference(reference_id: str):
        return workspace.store.get(reference_id, "implementation_reference")

    @app.get("/api/v1/implementations/{version_id}/runtime")
    def implementation_runtime(version_id: str, campaign_id: str):
        workspace.store.get(campaign_id, "campaign")
        return {**workspace.implementations.client.runtime(version_id),
            "receipts": [receipt for receipt in workspace.store.list("runtime_resolution_receipt", campaign_id) if receipt["version_id"] == version_id],
            "operations": [{key: effect.get(key) for key in ("id", "status", "receipt_id", "created_at")}
                           for effect in workspace.store.list("outbox", campaign_id)
                           if effect["kind"] == "implementation_resolve_runtime" and effect["version_id"] == version_id]}
