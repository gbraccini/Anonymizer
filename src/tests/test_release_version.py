from fastapi.testclient import TestClient

from anonymizer import __version__
from anonymizer.version import VERSION
from anonymizer.web.app import create_app


def test_release_version_is_visible_on_home_and_reported_by_health():
    with TestClient(
        create_app(local_only=True), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)
    ) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert f"Versione {VERSION}" in response.text
        assert "{{APP_VERSION}}" not in response.text
        assert client.get("/api/health").json()["version"] == VERSION == __version__
