"""Health, the built frontend and the catch-all that serves it for every page address."""
from pathlib import Path

from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles


def install(app, workspace, frontend_directory=None):
    @app.get("/api/health")
    def health():
        return {"status": "ok", "service": "balsamic", "max_workers": workspace.max_workers}

    dist = Path(frontend_directory).resolve() if frontend_directory is not None else Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def frontend(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "API route not found"}, status_code=404)
        if (dist / "index.html").is_file():
            # The page names the hashed bundle of the current build, so a browser must revalidate it on every load;
            # otherwise it keeps showing the previous build after an update until a forced reload.
            fresh = {"Cache-Control": "no-cache"}
            candidate = (dist / path).resolve()
            if candidate.is_relative_to(dist) and candidate.is_file():
                return FileResponse(candidate, headers=fresh if candidate.suffix == ".html" else None)
            return FileResponse(dist / "index.html", headers=fresh)
        return Response("Balsamic API is running. Build the workspace with npm ci && npm run build in frontend/.", media_type="text/plain")
