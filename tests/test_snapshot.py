"""Tests for the tenant snapshot store."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from sapsf_shared.cli import main
from sapsf_shared.exceptions import SFConfigError
from sapsf_shared.snapshot import SnapshotStore, parse_only


def test_create_snapshot_is_content_addressed_and_immutable(tmp_path: Path):
    store = SnapshotStore(tmp_path)
    first = store.create_snapshot(
        "demo",
        {"positions": [{"code": "P1", "title": "Analyst"}]},
        source_label="test",
    )
    second = store.create_snapshot(
        "demo",
        {"positions": [{"title": "Analyst", "code": "P1"}]},
        source_label="test",
    )

    assert second.snapshot_id == first.snapshot_id
    assert second.path == first.path
    assert (first.path / "snapshot.sqlite").stat().st_mode & 0o222 == 0


def test_selective_import_and_read_collection(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "metadata.json").write_text(json.dumps([{"id": "EmpJob"}]))
    (source / "picklists.json").write_text(json.dumps([{"externalCode": "country"}]))

    store = SnapshotStore(tmp_path / "store")
    ref = store.import_directory("demo", source, only={"metadata"})

    assert ref.collections == ("metadata",)
    assert store.read_collection(ref.snapshot_id, "metadata")[0]["id"] == "EmpJob"


def test_snapshot_rejects_credential_like_fields(tmp_path: Path):
    store = SnapshotStore(tmp_path)
    with pytest.raises(SFConfigError):
        store.create_snapshot("demo", {"metadata": [{"password": "secret"}]})


def test_diff_reports_added_removed_and_changed(tmp_path: Path):
    store = SnapshotStore(tmp_path)
    left = store.create_snapshot(
        "demo",
        {"positions": [{"code": "P1", "title": "Old"}, {"code": "P2", "title": "Gone"}]},
    )
    right = store.create_snapshot(
        "demo",
        {"positions": [{"code": "P1", "title": "New"}, {"code": "P3", "title": "Added"}]},
    )

    diff = store.diff(left.snapshot_id, right.snapshot_id)
    assert diff.added["positions"] == ["P3"]
    assert diff.removed["positions"] == ["P2"]
    assert diff.changed["positions"] == ["P1"]


def test_parse_only_validates_collection_names():
    assert parse_only("metadata,picklists") == {"metadata", "picklists"}
    with pytest.raises(SFConfigError):
        parse_only("metadata,passwords")


def test_cli_snapshot_pull_list_and_diff(tmp_path: Path, capsys):
    source_a = tmp_path / "a"
    source_b = tmp_path / "b"
    source_a.mkdir()
    source_b.mkdir()
    (source_a / "positions.json").write_text(json.dumps([{"code": "P1", "title": "A"}]))
    (source_b / "positions.json").write_text(json.dumps([{"code": "P1", "title": "B"}]))

    root = tmp_path / "store"
    assert (
        main(
            [
                "--root",
                str(root),
                "snapshot",
                "pull",
                "--tenant",
                "demo",
                "--from-dir",
                str(source_a),
            ]
        )
        == 0
    )
    first = json.loads(capsys.readouterr().out)["snapshot_id"]
    assert (
        main(
            [
                "--root",
                str(root),
                "snapshot",
                "pull",
                "--tenant",
                "demo",
                "--from-dir",
                str(source_b),
            ]
        )
        == 0
    )
    second = json.loads(capsys.readouterr().out)["snapshot_id"]

    assert main(["--root", str(root), "snapshot", "list", "--tenant", "demo"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert len(listed) == 2

    assert main(["--root", str(root), "snapshot", "diff", first, second]) == 0
    diff = json.loads(capsys.readouterr().out)
    assert diff["changed"]["positions"] == ["P1"]


def test_snapshot_sqlite_contains_no_credentials(tmp_path: Path):
    store = SnapshotStore(tmp_path)
    ref = store.create_snapshot("demo", {"metadata": [{"id": "safe"}]})

    with sqlite3.connect(ref.path / "snapshot.sqlite") as conn:
        rows = conn.execute("select json_data from item").fetchall()
    serialized = "\n".join(row[0] for row in rows).lower()
    assert "password" not in serialized
    assert "secret" not in serialized
