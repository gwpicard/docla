"""Command line interface for brands."""

import argparse
import sys
from pathlib import Path
from typing import Any

from docla.brand.changes import Evidence, begin_change, change_log, record_change
from docla.brand.git import GitError
from docla.brand.intake import material_files, take_in
from docla.brand.workspace import MATERIAL_CLASSES, BrandError, brand_path, default_root, init_brand


def add_brand_commands(subparsers: Any) -> None:
    brand = subparsers.add_parser("brand", help="work with brands")
    commands = brand.add_subparsers(dest="brand_command", required=True)
    init = commands.add_parser("init", help="initialise a brand")
    init.add_argument("slug")
    init.add_argument("--root", type=Path, default=default_root())
    log = commands.add_parser("log", help="list brand changes")
    log.add_argument("slug")
    log.add_argument("--root", type=Path, default=default_root())
    intake = commands.add_parser("intake", help="record brand materials")
    intake.add_argument("slug")
    intake.add_argument("--root", type=Path, default=default_root())


def _intake(brand: Path) -> int:
    if not material_files(brand):
        print("no materials")
        return 2
    begin_change(brand, "intake")
    manifest = take_in(brand)
    record_change(
        brand,
        what="Take in materials",
        why="Record the brand's materials",
        evidence=[Evidence(file=e.path, note=e.sha256) for e in manifest.files],
        before=[],
        after=[],
        formats=["slides", "doc"],
    )
    print(f"{len(manifest.files)} files")
    for role in (*MATERIAL_CLASSES, "unsorted"):
        print(f"{role}: {sum(entry.role == role for entry in manifest.files)}")
    return 0


def run_brand(args: argparse.Namespace) -> int:
    try:
        if args.brand_command == "init":
            print(init_brand(args.slug, args.root))
        elif args.brand_command == "intake":
            return _intake(brand_path(args.slug, args.root))
        else:
            records = change_log(brand_path(args.slug, args.root))
            for record in records:
                print(f"{record.id}  {record.created[:10]}  {record.what}")
            if not records:
                print("no changes")
    except (BrandError, GitError) as error:
        print(error, file=sys.stderr)
        return 2
    return 0
