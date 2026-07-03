"""Immutable local snapshot store for SAP SuccessFactors tenant data.

The store is deliberately offline-first: callers hand it already-fetched
collections and it writes a versioned SQLite snapshot plus a small manifest.
Live pulling can be layered on top without changing analytical tools that only
need to read snapshots.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sapsf_shared.exceptions import SFConfigError

SNAPSHOT_SCHEMA_VERSION = "sf-snapshot/v1"
DEFAULT_COLLECTIONS = ("metadata", "picklists", "foundation", "positions", "mdf", "rbp")
SECRET_KEY_RE = re.compile(
    r"(password|passwd|secret|token|authorization|api[_-]?key|private[_-]?key)",
    re.I,
)


@dataclass(frozen=True)
class SnapshotRef:
    """Reference to an immutable snapshot on disk."""

    tenant: str
    snapshot_id: str
    path: Path
    created_at: str
    collections: tuple[str, ...]
    item_count: int


@dataclass(frozen=True)
class SnapshotDiff:
    """Collection-level diff between two snapshots."""

    left: str
    right: str
    added: dict[str, list[str]]
    removed: dict[str, list[str]]
    changed: dict[str, list[str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "left": self.left,
            "right": self.right,
            "added": self.added,
            "removed": self.removed,
            "changed": self.changed,
        }


class SnapshotStore:
    """Content-addressed snapshot store rooted at ``~/.sf-toolkit`` by default."""

    def __init__(self, root: Path | str | None = None) -> None:
        base = Path(root) if root else Path.home() / ".sf-toolkit"
        self.root = base.expanduser()
        self.snapshots_root = self.root / "snapshots"

    def create_snapshot(
        self,
        tenant: str,
        collections: dict[str, Any],
        *,
        source_label: str = "manual",
        created_at: datetime | None = None,
    ) -> SnapshotRef:
        """Write an immutable SQLite snapshot, reusing an existing one if unchanged."""
        clean_tenant = _safe_name(tenant)
        normalized = _normalize_collections(collections)
        _assert_no_secrets(normalized)

        content_hash = _hash_json(
            {
                "schema_version": SNAPSHOT_SCHEMA_VERSION,
                "tenant": clean_tenant,
                "collections": normalized,
            }
        )
        existing = self.get_snapshot(content_hash, tenant=clean_tenant)
        if existing:
            return existing

        when = (created_at or datetime.now(UTC)).replace(microsecond=0)
        dir_name = f"{when.strftime('%Y%m%dT%H%M%SZ')}_{content_hash[:12]}"
        final_dir = self.snapshots_root / clean_tenant / dir_name
        final_dir.parent.mkdir(parents=True, exist_ok=True)

        tmp_dir = Path(tempfile.mkdtemp(prefix=f".{dir_name}.", dir=str(final_dir.parent)))
        try:
            db_path = tmp_dir / "snapshot.sqlite"
            item_count = _write_sqlite(db_path, content_hash, clean_tenant, normalized)
            manifest = {
                "schema_version": SNAPSHOT_SCHEMA_VERSION,
                "tenant": clean_tenant,
                "snapshot_id": content_hash,
                "created_at": when.isoformat().replace("+00:00", "Z"),
                "source_label": source_label,
                "collections": sorted(normalized),
                "item_count": item_count,
                "sqlite": "snapshot.sqlite",
            }
            (tmp_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(tmp_dir, final_dir)
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

        return self.get_snapshot(content_hash, tenant=clean_tenant)  # type: ignore[return-value]

    def import_directory(
        self,
        tenant: str,
        source_dir: Path | str,
        *,
        only: set[str] | None = None,
        source_label: str | None = None,
    ) -> SnapshotRef:
        """Create a snapshot from ``<collection>.json`` files in a directory."""
        src = Path(source_dir)
        if not src.is_dir():
            raise SFConfigError(f"Snapshot source directory not found: {src}")

        selected = only or {p.stem for p in src.glob("*.json")}
        collections: dict[str, Any] = {}
        for name in sorted(selected):
            path = src / f"{name}.json"
            if not path.exists():
                raise SFConfigError(f"Snapshot collection file not found: {path}")
            collections[name] = json.loads(path.read_text(encoding="utf-8"))
        return self.create_snapshot(
            tenant,
            collections,
            source_label=source_label or str(src),
        )

    def list_snapshots(self, tenant: str | None = None) -> list[SnapshotRef]:
        """Return known snapshots ordered newest first."""
        roots: list[Path]
        if tenant:
            roots = [self.snapshots_root / _safe_name(tenant)]
        else:
            roots = [p for p in self.snapshots_root.glob("*") if p.is_dir()]

        refs: list[SnapshotRef] = []
        for root in roots:
            for manifest in root.glob("*/manifest.json"):
                ref = _read_ref(manifest)
                if ref:
                    refs.append(ref)
        return sorted(refs, key=lambda ref: ref.created_at, reverse=True)

    def get_snapshot(self, snapshot_id: str, *, tenant: str | None = None) -> SnapshotRef | None:
        """Resolve a snapshot by full id or unique prefix."""
        matches = [
            ref
            for ref in self.list_snapshots(tenant)
            if ref.snapshot_id == snapshot_id or ref.snapshot_id.startswith(snapshot_id)
        ]
        if not matches:
            return None
        if len(matches) > 1:
            raise SFConfigError(f"Snapshot id prefix is ambiguous: {snapshot_id}")
        return matches[0]

    def read_collection(self, snapshot_id: str, collection: str) -> list[dict[str, Any]]:
        """Read all records from one collection in a snapshot."""
        ref = self._require_snapshot(snapshot_id)
        with sqlite3.connect(ref.path / "snapshot.sqlite") as conn:
            rows = conn.execute(
                "select json_data from item where collection = ? order by item_key",
                (collection,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def diff(self, left_id: str, right_id: str) -> SnapshotDiff:
        """Compare two snapshots by collection/item content hash."""
        left = self._require_snapshot(left_id)
        right = self._require_snapshot(right_id)
        left_items = _load_item_hashes(left.path / "snapshot.sqlite")
        right_items = _load_item_hashes(right.path / "snapshot.sqlite")
        collections = sorted(set(left_items) | set(right_items))

        added: dict[str, list[str]] = {}
        removed: dict[str, list[str]] = {}
        changed: dict[str, list[str]] = {}
        for collection in collections:
            left_map = left_items.get(collection, {})
            right_map = right_items.get(collection, {})
            added[collection] = sorted(set(right_map) - set(left_map))
            removed[collection] = sorted(set(left_map) - set(right_map))
            changed[collection] = sorted(
                key for key in set(left_map) & set(right_map) if left_map[key] != right_map[key]
            )
        return SnapshotDiff(left.snapshot_id, right.snapshot_id, added, removed, changed)

    def _require_snapshot(self, snapshot_id: str) -> SnapshotRef:
        ref = self.get_snapshot(snapshot_id)
        if not ref:
            raise SFConfigError(f"Snapshot not found: {snapshot_id}")
        return ref


def parse_only(value: str | None) -> set[str] | None:
    """Parse ``--only metadata,picklists`` style collection filters."""
    if not value:
        return None
    requested = {part.strip() for part in value.split(",") if part.strip()}
    unknown = requested - set(DEFAULT_COLLECTIONS)
    if unknown:
        raise SFConfigError(f"Unknown snapshot collection(s): {', '.join(sorted(unknown))}")
    return requested


def _normalize_collections(collections: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    normalized: dict[str, list[dict[str, Any]]] = {}
    for name, raw in collections.items():
        if raw is None:
            continue
        if isinstance(raw, dict) and "results" in raw:
            records = raw["results"]
        elif isinstance(raw, list):
            records = raw
        else:
            records = [raw]
        normalized[_safe_name(name)] = [_record_with_key(record) for record in records]
    if not normalized:
        raise SFConfigError("Snapshot must contain at least one collection")
    return normalized


def _record_with_key(record: Any) -> dict[str, Any]:
    clean = dict(record) if isinstance(record, dict) else {"value": record}
    clean.setdefault("_snapshot_key", _derive_key(clean))
    return clean


def _derive_key(record: dict[str, Any]) -> str:
    for field in ("id", "externalCode", "code", "userId", "roleId", "name"):
        value = record.get(field)
        if value not in (None, ""):
            return str(value)
    return _hash_json(record)[:16]


def _assert_no_secrets(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if SECRET_KEY_RE.search(str(key)):
                raise SFConfigError(
                    f"Refusing to write credential-like field to snapshot: {path}.{key}"
                )
            _assert_no_secrets(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_secrets(item, f"{path}[{index}]")


def _write_sqlite(
    db_path: Path,
    snapshot_id: str,
    tenant: str,
    collections: dict[str, list[dict[str, Any]]],
) -> int:
    with sqlite3.connect(db_path) as conn:
        conn.execute("pragma journal_mode=off")
        conn.execute(
            "create table snapshot (snapshot_id text primary key, tenant text, schema_version text)"
        )
        conn.execute("create table collection (name text primary key, item_count integer not null)")
        conn.execute(
            "create table item (collection text, item_key text, item_hash text, json_data text, primary key (collection, item_key))"
        )
        conn.execute(
            "insert into snapshot values (?, ?, ?)",
            (snapshot_id, tenant, SNAPSHOT_SCHEMA_VERSION),
        )
        item_count = 0
        for collection, records in sorted(collections.items()):
            conn.execute("insert into collection values (?, ?)", (collection, len(records)))
            for record in records:
                item_key = str(record["_snapshot_key"])
                json_data = json.dumps(record, sort_keys=True, separators=(",", ":"))
                conn.execute(
                    "insert into item values (?, ?, ?, ?)",
                    (collection, item_key, _hash_text(json_data), json_data),
                )
                item_count += 1
    db_path.chmod(0o444)
    return item_count


def _load_item_hashes(db_path: Path) -> dict[str, dict[str, str]]:
    items: dict[str, dict[str, str]] = {}
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("select collection, item_key, item_hash from item").fetchall()
    for collection, item_key, item_hash in rows:
        items.setdefault(collection, {})[item_key] = item_hash
    return items


def _read_ref(manifest_path: Path) -> SnapshotRef | None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return SnapshotRef(
            tenant=manifest["tenant"],
            snapshot_id=manifest["snapshot_id"],
            path=manifest_path.parent,
            created_at=manifest["created_at"],
            collections=tuple(manifest.get("collections", ())),
            item_count=int(manifest.get("item_count", 0)),
        )
    except Exception:
        return None


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip()).strip("-")
    if not safe:
        raise SFConfigError("Snapshot tenant/collection name cannot be empty")
    return safe


def _hash_json(value: Any) -> str:
    return _hash_text(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str))


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
