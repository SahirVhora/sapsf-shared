"""Command-line entry point for shared SAP SuccessFactors tooling."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sapsf_shared.exceptions import SFConfigError
from sapsf_shared.snapshot import SnapshotStore, parse_only


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sf", description="SAP SuccessFactors toolkit")
    parser.add_argument("--root", type=Path, default=None, help="Override ~/.sf-toolkit root")
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot = subparsers.add_parser("snapshot", help="Manage local tenant snapshots")
    snapshot_sub = snapshot.add_subparsers(dest="snapshot_command", required=True)

    pull = snapshot_sub.add_parser("pull", help="Create a local snapshot")
    pull.add_argument("--tenant", required=True, help="Tenant alias")
    pull.add_argument("--from-dir", type=Path, help="Directory containing <collection>.json files")
    pull.add_argument("--only", help="Comma-separated collections, e.g. metadata,picklists")

    list_cmd = snapshot_sub.add_parser("list", help="List snapshots")
    list_cmd.add_argument("--tenant", help="Filter by tenant alias")

    show = snapshot_sub.add_parser("show", help="Show one snapshot manifest")
    show.add_argument("snapshot_id")

    diff = snapshot_sub.add_parser("diff", help="Diff two snapshots")
    diff.add_argument("left")
    diff.add_argument("right")

    args = parser.parse_args(argv)
    store = SnapshotStore(args.root)

    try:
        if args.command == "snapshot":
            return _snapshot_main(args, store)
    except SFConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1


def _snapshot_main(args: argparse.Namespace, store: SnapshotStore) -> int:
    if args.snapshot_command == "pull":
        if not args.from_dir:
            raise SFConfigError(
                "Live tenant pull is not wired yet; pass --from-dir for offline snapshot import"
            )
        ref = store.import_directory(args.tenant, args.from_dir, only=parse_only(args.only))
        print(
            json.dumps(
                {
                    "snapshot_id": ref.snapshot_id,
                    "tenant": ref.tenant,
                    "path": str(ref.path),
                    "item_count": ref.item_count,
                    "collections": list(ref.collections),
                },
                indent=2,
            )
        )
        return 0

    if args.snapshot_command == "list":
        refs = store.list_snapshots(args.tenant)
        print(
            json.dumps(
                [
                    {
                        "snapshot_id": ref.snapshot_id,
                        "tenant": ref.tenant,
                        "created_at": ref.created_at,
                        "item_count": ref.item_count,
                        "collections": list(ref.collections),
                        "path": str(ref.path),
                    }
                    for ref in refs
                ],
                indent=2,
            )
        )
        return 0

    if args.snapshot_command == "show":
        ref = store._require_snapshot(args.snapshot_id)
        print((ref.path / "manifest.json").read_text(encoding="utf-8"))
        return 0

    if args.snapshot_command == "diff":
        print(json.dumps(store.diff(args.left, args.right).to_dict(), indent=2, sort_keys=True))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
