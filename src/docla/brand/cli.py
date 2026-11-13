"""Command line interface for brands."""

import argparse
import sys
from pathlib import Path
from typing import Any

from docla.brand.changes import change_log
from docla.brand.git import GitError
from docla.brand.workspace import BrandError, brand_path, default_root, init_brand


def add_brand_commands(subparsers: Any) -> None:
    brand = subparsers.add_parser("brand", help="work with brands")
    commands = brand.add_subparsers(dest="brand_command", required=True)
    init = commands.add_parser("init", help="initialise a brand")
    init.add_argument("slug")
    init.add_argument("--root", type=Path, default=default_root())
    log = commands.add_parser("log", help="list brand changes")
    log.add_argument("slug")
    log.add_argument("--root", type=Path, default=default_root())


def run_brand(args: argparse.Namespace) -> int:
    try:
        if args.brand_command == "init":
            print(init_brand(args.slug, args.root))
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
