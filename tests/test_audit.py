import json

from sapsf_shared.audit import audit_log


def test_audit_log_uses_runtime_env_path(monkeypatch, tmp_path):
    first = tmp_path / "first" / "audit.jsonl"
    second = tmp_path / "second" / "audit.jsonl"

    monkeypatch.setenv("SAPSF_AUDIT_LOG", str(first))
    audit_log("tool", "first_action", "success")

    monkeypatch.setenv("SAPSF_AUDIT_LOG", str(second))
    audit_log("tool", "second_action", "success")

    assert first.exists()
    assert second.exists()
    assert json.loads(first.read_text(encoding="utf-8"))["action"] == "first_action"
    assert json.loads(second.read_text(encoding="utf-8"))["action"] == "second_action"


def test_audit_log_writes_utf8_json(monkeypatch, tmp_path):
    path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("SAPSF_AUDIT_LOG", str(path))

    audit_log(
        "tool",
        "scan",
        "success",
        details="Malmö 北京 tenant checked",
        tenant="Tēnant",
    )

    raw = path.read_text(encoding="utf-8")
    assert "Malmö 北京" in raw
    assert "\\u5317" not in raw
    event = json.loads(raw)
    assert event["details"] == "Malmö 北京 tenant checked"
    assert event["tenant"] == "Tēnant"
