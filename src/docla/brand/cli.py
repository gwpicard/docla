"""Command line interface for brands."""

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from docla.brand.changes import Evidence, begin_change, change_log, record_change
from docla.brand.fonts import check_fonts, font_paths, install_fonts, write_report
from docla.brand.gaps import check_gaps
from docla.brand.git import GitError
from docla.brand.intake import MANIFEST, material_files, take_in
from docla.brand.pages import load_manifest, parse_pdfs
from docla.brand.questions import add_questions, open_questions
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
    parse = commands.add_parser("parse", help="index PDF pages")
    parse.add_argument("slug")
    parse.add_argument("--root", type=Path, default=default_root())
    fonts = commands.add_parser("fonts", help="check brand fonts")
    fonts.add_argument("slug")
    fonts.add_argument("--root", type=Path, default=default_root())
    gaps = commands.add_parser("gaps", help="check missing brand materials")
    gaps.add_argument("slug")
    gaps.add_argument("--root", type=Path, default=default_root())
    templates = commands.add_parser("templates", help="read PowerPoint templates")
    templates.add_argument("slug")
    templates.add_argument("--root", type=Path, default=default_root())


def _templates(brand: Path) -> int:
    from docla.brand.templates import read_templates

    manifest = load_manifest(brand)
    if not any(e.type in ("pptx", "potx") and e.unread is None for e in manifest.files):
        print("no readable PowerPoint templates")
        return 2
    begin_change(brand, "templates")
    report = read_templates(brand)
    if report.templates:
        record_change(
            brand,
            what="Read the brand's templates",
            why="Template values are measured, not guessed",
            evidence=[Evidence(file=t.source, note=f"{len(t.layouts)} layouts") for t in report.templates],
            before=[],
            after=[],
            formats=sorted({t.format for t in report.templates}),
        )
    for template in report.templates:
        print(f"{template.source}  {template.format}  {len(template.layouts)} layouts  {len(template.colours)} colours")
    for item in report.unread:
        print(f"{item.file}  unread: {item.reason}")
    return 0


def _parse(brand: Path) -> int:
    manifest = load_manifest(brand)
    if not any(entry.type == "pdf" and entry.unread is None for entry in manifest.files):
        print("no readable PDFs")
        return 2
    begin_change(brand, "parse")
    index = parse_pdfs(brand)
    counts = Counter(page.file for page in index.pages)
    record_change(
        brand,
        what="Parse the brand's PDFs",
        why="Later stages read pages from one index",
        evidence=[Evidence(file=file, note=f"{count} pages") for file, count in counts.items()],
        before=[],
        after=[],
        formats=["slides", "doc"],
    )
    for file, count in counts.items():
        print(f"{file}  {count} pages")
    for skipped in index.skipped:
        print(f"{skipped.file}  skipped: {skipped.reason}")
    return 0


def _gaps(brand: Path) -> int:
    if not (brand / MANIFEST).exists():
        raise BrandError("Run docla brand intake first")
    begin_change(brand, "gaps")
    gaps, identities = check_gaps(brand)
    record_change(
        brand,
        what="Record what the brand does not provide",
        why="Every gap is a question or a recorded decision",
        evidence=[Evidence(file=MANIFEST.as_posix())]
        + [Evidence(file=i.file, page=i.page, quote=i.quote) for i in identities],
        before=[],
        after=[],
        formats=["slides", "doc"],
    )
    for gap in gaps:
        print(f"{gap.kind}  {gap.format or '-'}")
    for identity in identities:
        print(f"{identity.file}  version {identity.version or '?'}  {identity.date or '?'}")
    print(f"{len(open_questions(brand))} open questions")
    return 0


def _fonts(brand: Path) -> int:
    if not font_paths(brand):
        print("no font files")
        return 2
    begin_change(brand, "fonts")
    report = check_fonts(brand)
    install_fonts(brand, report)
    write_report(brand, report)
    add_questions(brand, report.questions)
    record_change(
        brand,
        what="Check the brand's fonts",
        why="Fonts are checked before anything is learnt",
        evidence=[Evidence(file=f"materials/fonts/{f.file}", note=f.status) for f in report.files],
        before=[],
        after=[],
        formats=["slides", "doc"],
    )
    for font in report.files:
        print(f"{font.file}  {font.family} {font.weight}  {font.embedding}  {font.status}")
    print(f"{len(open_questions(brand))} open questions")
    return 0


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
        elif args.brand_command == "parse":
            return _parse(brand_path(args.slug, args.root))
        elif args.brand_command == "fonts":
            return _fonts(brand_path(args.slug, args.root))
        elif args.brand_command == "gaps":
            return _gaps(brand_path(args.slug, args.root))
        elif args.brand_command == "templates":
            return _templates(brand_path(args.slug, args.root))
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
