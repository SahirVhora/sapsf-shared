"""Tests for sapsf_shared.flask_base."""

import json

from sapsf_shared.flask_base import create_app


class TestSFApp:
    def test_app_created(self):
        app = create_app("test_app")
        assert app is not None
        assert app.name == "test_app"

    def test_health_endpoint(self):
        app = create_app("test_app")
        with app.test_client() as client:
            resp = client.get("/api/health")
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert data["status"] == "ok"
            assert data["service"] == "test_app"

    def test_cors_headers_on_health(self):
        app = create_app("test_app")
        with app.test_client() as client:
            resp = client.get("/api/health", headers={"Origin": "http://localhost"})
            assert resp.headers.get("Access-Control-Allow-Origin") == "http://localhost"

    def test_options_handler(self):
        app = create_app("test_app")
        with app.test_client() as client:
            resp = client.options("/")
            assert resp.status_code == 204

    def test_404_handler(self):
        app = create_app("test_app")
        with app.test_client() as client:
            resp = client.get("/nonexistent")
            assert resp.status_code == 404
            data = json.loads(resp.data)
            assert "Not found" in data["error"]

    def test_500_handler(self):
        app = create_app("test_app")

        @app.route("/boom")
        def boom():
            raise RuntimeError("intentional")

        with app.test_client() as client:
            resp = client.get("/boom")
            assert resp.status_code == 500
            data = json.loads(resp.data)
            assert "Internal server error" in data["error"]

    def test_csrf_token_generation(self):
        app = create_app("test_app", enable_csrf=True)
        with app.test_request_context():
            token = app._get_csrf_token()
            assert len(token) > 0

    def test_csrf_rejects_missing_token(self):
        app = create_app("test_app", enable_csrf=True)

        @app.route("/post", methods=["POST"])
        def post_handler():
            return "ok"

        with app.test_client() as client:
            resp = client.post("/post", data={"key": "val"})
            assert resp.status_code == 403

    def test_csrf_accepts_valid_token(self):
        app = create_app("test_app", enable_csrf=True)

        @app.route("/post", methods=["POST"])
        def post_handler():
            return "ok"

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["csrf_token"] = "test_token"
            resp = client.post("/post", data={"csrf_token": "test_token"})
            assert resp.status_code == 200

    def test_csrf_disabled(self):
        app = create_app("test_app", enable_csrf=False)

        @app.route("/post", methods=["POST"])
        def post_handler():
            return "ok"

        with app.test_client() as client:
            resp = client.post("/post", data={"key": "val"})
            assert resp.status_code == 200

    def test_secret_key_from_env(self, monkeypatch):
        monkeypatch.setenv("FLASK_SECRET_KEY", "from_env")
        app = create_app("test_app")
        assert app.secret_key == "from_env"

    def test_auto_secret_key(self):
        app = create_app("test_app")
        assert len(app.secret_key) > 0
