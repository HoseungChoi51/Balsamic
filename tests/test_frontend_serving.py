"""The built dashboard is served so that a browser picks up a new build on its next load."""
from fastapi.testclient import TestClient

from optimization_framework.api.app import create_app


def test_the_page_is_revalidated_on_every_load_and_the_hashed_bundle_is_not(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<script src="/assets/index-abc123.js"></script>')
    (dist / "assets" / "index-abc123.js").write_text("console.log('build')")
    client = TestClient(create_app(tmp_path / "data", start_workers=False, frontend_directory=dist))
    for path in ("/", "/index.html", "/reports"):
        response = client.get(path)
        assert response.status_code == 200 and "index-abc123.js" in response.text
        assert response.headers["cache-control"] == "no-cache"
    bundle = client.get("/assets/index-abc123.js")
    assert bundle.status_code == 200 and "cache-control" not in bundle.headers
