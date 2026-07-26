"""Tests for sapsf_shared.flask_base."""

import json

from sapsf_shared.flask_base import check_local_token, create_app, require_local_token


class TestSFApp:
    def test_flask_helpers_are_direct_but_not_wildcard_exports(self):
        import sapsf_shared

        assert sapsf_shared.require_local_token is require_local_token
        assert sapsf_shared.check_local_token is check_local_token
        assert "require_local_token" not in sapsf_shared.__all__
        assert "check_local_token" not in sapsf_shared.__all__

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

    def test_cors_allows_allowlisted_origin(self):
        app = create_app("test_app", cors_origins=["http://localhost"])
        with app.test_client() as client:
            resp = client.get("/api/health", headers={"Origin": "http://localhost"})
            assert resp.headers.get("Access-Control-Allow-Origin") == "http://localhost"

    def test_cors_allows_both_supported_token_headers(self):
        app = create_app("test_app", cors_origins=["http://localhost"])
        with app.test_client() as client:
            resp = client.options(
                "/api/health",
                headers={"Origin": "http://localhost"},
            )
        allowed = resp.headers["Access-Control-Allow-Headers"]
        assert "X-Report-Token" in allowed
        assert "X-Auth-Token" in allowed

    def test_cors_rejects_unlisted_origin(self):
        app = create_app("test_app", cors_origins=["http://localhost"])
        with app.test_client() as client:
            resp = client.get("/api/health", headers={"Origin": "http://evil.example"})
            assert resp.headers.get("Access-Control-Allow-Origin") is None

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


class TestLocalTokenHelpers:
    @staticmethod
    def _decorated_app(token: str | None, header_name: str = "X-Report-Token"):
        app = create_app("token_test", enable_csrf=False)

        @app.get("/protected")
        @require_local_token(lambda: token, header_name=header_name)
        def protected():
            return {"ok": True}

        return app

    def test_require_local_token_accepts_matching_header(self):
        app = self._decorated_app("expected")
        with app.test_client() as client:
            resp = client.get("/protected", headers={"X-Report-Token": "expected"})
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True}

    def test_require_local_token_supports_custom_header(self):
        app = self._decorated_app("expected", "X-Auth-Token")
        with app.test_client() as client:
            resp = client.get("/protected", headers={"X-Auth-Token": "expected"})
        assert resp.status_code == 200

    def test_require_local_token_rejects_query_even_with_valid_header(self, caplog):
        app = self._decorated_app("expected")
        with app.test_client() as client, caplog.at_level("WARNING"):
            resp = client.get(
                "/protected?token=expected",
                headers={"X-Report-Token": "expected"},
            )
        assert resp.status_code == 401
        assert "reason=legacy_query" in caplog.text
        assert "path=/protected" in caplog.text
        assert "remote=127.0.0.1" in caplog.text

    def test_require_local_token_rejects_missing_or_wrong_header(self, caplog):
        app = self._decorated_app("expected")
        with app.test_client() as client, caplog.at_level("WARNING"):
            missing = client.get("/protected")
            wrong = client.get("/protected", headers={"X-Report-Token": "not-expected"})
        assert missing.status_code == 403
        assert wrong.status_code == 403
        assert caplog.text.count("reason=missing_or_invalid_header") == 2

    def test_require_local_token_fails_closed_when_unconfigured(self, caplog):
        app = self._decorated_app(None)
        with app.test_client() as client, caplog.at_level("WARNING"):
            resp = client.get("/protected")
        assert resp.status_code == 503
        assert "reason=not_configured" in caplog.text
        assert "path=/protected" in caplog.text
        assert "remote=127.0.0.1" in caplog.text

    def test_check_local_token_preserves_open_unconfigured_behavior(self, caplog):
        app = create_app("token_test", enable_csrf=False)
        with app.test_request_context("/report"), caplog.at_level("WARNING"):
            assert check_local_token(None)
        assert not caplog.text

    def test_check_local_token_prefers_header_without_warning(self, caplog):
        app = create_app("token_test", enable_csrf=False)
        with (
            app.test_request_context("/report", headers={"X-Report-Token": "expected"}),
            caplog.at_level("WARNING"),
        ):
            assert check_local_token("expected")
        assert not caplog.text

    def test_check_local_token_accepts_legacy_query_once_with_warning(self, caplog):
        app = create_app("token_test", enable_csrf=False)
        with app.test_client() as client, caplog.at_level("WARNING"):

            @app.get("/report")
            def report():
                return ({"ok": check_local_token("expected")}, 200)

            resp = client.get("/report?token=expected")
        assert resp.get_json() == {"ok": True}
        assert caplog.text.count("accepted deprecated query token") == 1
        assert "path=/report" in caplog.text
        assert "remote=127.0.0.1" in caplog.text

    def test_check_local_token_rejects_and_logs_once(self, caplog):
        app = create_app("token_test", enable_csrf=False)
        with (
            app.test_request_context(
                "/report?token=wrong", environ_base={"REMOTE_ADDR": "127.0.0.1"}
            ),
            caplog.at_level("WARNING"),
        ):
            assert not check_local_token("expected")
        assert caplog.text.count("rejected request") == 1
        assert "path=/report" in caplog.text
        assert "remote=127.0.0.1" in caplog.text

    def test_lazy_exports_remain_visible_without_hiding_module_globals(self):
        import sapsf_shared

        names = dir(sapsf_shared)
        assert "require_local_token" in names
        assert "check_local_token" in names
        assert "__name__" in names
