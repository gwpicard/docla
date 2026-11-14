"""Command line interface for brands."""

import argparse
import asyncio
import re
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from docla.brand import agents
from docla.brand.changes import Evidence, begin_change, change_log, record_change
from docla.brand.claims import extract_claims, load_claims
from docla.brand.departures import _proposal, set_token
from docla.brand.fonts import check_fonts, font_paths, install_fonts, write_report
from docla.brand.gaps import check_gaps
from docla.brand.git import GitError, run_git
from docla.brand.illustrative import illustrative_questions
from docla.brand.intake import MANIFEST, material_files, take_in
from docla.brand.measure import _collect, measure_brand
from docla.brand.pages import load_manifest, parse_pdfs
from docla.brand.questions import add_questions, drop_open_questions, load_questions, open_questions
from docla.brand.roles import load_roles, record_roles
from docla.brand.segment import load_topics, segment_needed, segment_pages, topic_groups
from docla.brand.tokenmap import tie_claims
from docla.brand.workspace import MATERIAL_CLASSES, BrandError, brand_path, default_root, init_brand
from docla.facts.pdf import PdfPlumberFacts
from docla.theme import ThemeError
from docla.theme.labels import ValueProvenance, ValueSource


def add_brand_commands(subparsers: Any) -> None:
    brand = subparsers.add_parser("brand", help="work with brands")
    commands = brand.add_subparsers(dest="brand_command", required=True)
    set_parser = commands.add_parser("set", help="change a theme token")
    set_parser.add_argument("slug")
    set_parser.add_argument("path")
    set_parser.add_argument("value")
    set_parser.add_argument("--reason", required=True)
    set_parser.add_argument("--approve", action="store_true")
    set_parser.add_argument("--root", type=Path, default=default_root())
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
    roles = commands.add_parser("roles", help="map pages to components")
    roles.add_argument("slug")
    roles.add_argument("--root", type=Path, default=default_root())
    roles.add_argument("--map", action="append", default=[])
    roles.add_argument("--unmap", action="append", default=[])
    roles.add_argument("--note")
    segment = commands.add_parser("segment", help="sort guideline pages into topics")
    segment.add_argument("slug")
    segment.add_argument("--root", type=Path, default=default_root())
    extract = commands.add_parser("extract", help="extract guideline claims")
    extract.add_argument("slug")
    extract.add_argument("--root", type=Path, default=default_root())
    tie = commands.add_parser("tie", help="tie claims to tokens")
    tie.add_argument("slug")
    tie.add_argument("--root", type=Path, default=default_root())
    fonts = commands.add_parser("fonts", help="check brand fonts")
    fonts.add_argument("slug")
    fonts.add_argument("--root", type=Path, default=default_root())
    gaps = commands.add_parser("gaps", help="check missing brand materials")
    gaps.add_argument("slug")
    gaps.add_argument("--root", type=Path, default=default_root())
    templates = commands.add_parser("templates", help="read PowerPoint templates")
    templates.add_argument("slug")
    templates.add_argument("--root", type=Path, default=default_root())
    reconcile_parser = commands.add_parser("reconcile", help="reconcile brand sources")
    reconcile_parser.add_argument("slug")
    reconcile_parser.add_argument("--root", type=Path, default=default_root())
    measure = commands.add_parser("measure", help="measure brand pages")
    measure.add_argument("slug")
    measure.add_argument("--root", type=Path, default=default_root())
    synthesise = commands.add_parser("synthesise", help="synthesise brand tokens")
    synthesise.add_argument("slug")
    synthesise.add_argument("--root", type=Path, default=default_root())


def _synthesise(brand: Path) -> int:
    from docla.brand.reconcile import load_reconciliation
    from docla.brand.synth_rules import synthesise_rules
    from docla.brand.synth_tokens import synthesise_tokens
    from docla.brand.synth_voice import synthesise_voice

    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        shutil.copytree(brand / "theme", temporary / "theme")
        synthesise_tokens(temporary)
    reconciliation = load_reconciliation(brand)
    begin_change(brand, "synthesise")
    result = synthesise_tokens(brand)
    rule_result = None
    if (brand / "theme/ingest/claims.json").exists():
        rule_result = asyncio.run(synthesise_rules(brand, agents.brand_claude(brand)))
    voice_result = asyncio.run(synthesise_voice(brand, agents.brand_claude(brand)))
    evidence: dict[tuple[str, int | None], Evidence] = {}
    for item in reconciliation.values:
        source = item.provenance.source
        for file in ([source.file] if source.file else []) + source.files:
            evidence.setdefault((file, source.page), Evidence(file=file, page=source.page, quote=source.quote))
    if rule_result is not None:
        for ident in rule_result.rules:
            path = brand / "theme/rules/ingested" / f"{ident}.yaml"
            rule_source = (yaml.safe_load(path.read_text()) or {}).get("provenance", {}).get("source", {})
            rule_file = rule_source.get("file") or next(iter(rule_source.get("files", [])), None)
            if rule_file:
                evidence.setdefault(
                    (rule_file, rule_source.get("page")),
                    Evidence(file=rule_file, page=rule_source.get("page"), quote=rule_source.get("quote")),
                )
    record_change(
        brand,
        what="Synthesise the brand theme",
        why="Tokens come from the reconciled sources, each with its label",
        evidence=list(evidence.values()),
        before=[],
        after=[],
        formats=["slides", "doc"],
    )
    for label, count in result.labels.items():
        print(f"{label}: {count}")
    for inferred_path in result.inferred:
        print(inferred_path)
    if rule_result is not None:
        print(f"{len(rule_result.rules)} rules, {len(rule_result.rubric)} rubric questions")
    print(
        f"{len(voice_result.banned)} banned terms, {len(voice_result.terminology)} preferred terms, "
        f"{len(voice_result.required)} required elements"
    )
    print(f"{len(open_questions(brand))} open questions")
    return 0


def _reconcile(brand: Path) -> int:
    from docla.brand.measure import MEASURE
    from docla.brand.reconcile import TEMPLATES, reconcile
    from docla.brand.tokenmap import TOKEN_CLAIMS

    if not any((brand / path).exists() for path in (MEASURE, TEMPLATES, TOKEN_CLAIMS)):
        raise BrandError("Run docla brand tie, docla brand templates or docla brand measure first")
    begin_change(brand, "reconcile")
    result = reconcile(brand)
    evidence = [
        Evidence(
            file=i.candidates[0].source.file or "theme/ingest/measure.json",
            page=i.candidates[0].source.page,
            quote=i.candidates[0].source.quote,
        )
        for i in result.values
        if i.status == "conflict"
    ]
    record_change(
        brand,
        what="Reconcile the brand's sources",
        why="Agreements settle values; conflicts become questions",
        evidence=evidence or [Evidence(file="theme/ingest/reconcile.json")],
        before=[],
        after=[],
        formats=["slides", "doc"],
    )
    counts = Counter(i.status for i in result.values)
    for status in ("agreed", "single", "conflict", "proposed"):
        print(f"{status}: {counts[status]}")
    print(f"{len(result.proposed_rules)} proposed rules")
    print(f"{len(open_questions(brand))} open questions")
    return 0


def _measure(brand: Path) -> int:
    if not _collect(brand, None, PdfPlumberFacts()).sets:
        print("no pages measured")
        return 2
    begin_change(brand, "measure")
    result = measure_brand(brand)
    counts = Counter(page.file for item in result.sets for page in item.pages)
    record_change(
        brand,
        what="Measure the brand's pages",
        why="Measured values are compared with what the guidelines state",
        evidence=[Evidence(file=file, note=f"{count} pages measured") for file, count in counts.items()],
        before=[],
        after=[],
        formats=sorted({item.format for item in result.sets}),
    )
    for item in result.sets:
        margins = "/".join(f"{item.margin[side].value:g}" for side in ("top", "right", "bottom", "left"))
        print(
            f"{item.kind}  {item.format}  {len(item.pages)} pages  margins {margins} pt"
            f"  body {item.body_size.value:g} pt"
        )
    for page in result.skipped:
        print(f"{page.file}  page {page.page}  skipped: {page.reason}")
    return 0


def _tie(brand: Path) -> int:
    load_claims(brand)
    begin_change(brand, "tie")
    result = asyncio.run(tie_claims(brand, agents.brand_claude(brand)))
    evidence = [Evidence(file=i.source.file, page=i.source.page, quote=i.source.quote) for i in result.items]
    record_change(
        brand,
        what="Tie the guidelines' claims to tokens",
        why="Claims are compared with measurements token by token",
        evidence=evidence or [Evidence(file="theme/ingest/claims.json")],
        before=[],
        after=[],
        formats=["slides", "doc"],
    )
    print(f"{len(result.items)} token values, {len(result.refused)} refused")
    for item in result.items:
        print(f"{item.path}  {item.value}")
    return 0


def _extract(brand: Path) -> int:
    topics = load_topics(brand)
    begin_change(brand, "extract")
    result = asyncio.run(extract_claims(brand, agents.brand_claude(brand)))
    questions = illustrative_questions(result.claims)
    add_questions(brand, questions)
    current_ids = {question.id for question in questions}
    drop_open_questions(
        brand,
        [q.id for q in load_questions(brand) if q.id.startswith("claim.illustrative.") and q.id not in current_ids],
    )
    evidence = [Evidence(file=s.file, page=s.page, quote=s.quote) for claim in result.claims for s in claim.sources[:1]]
    record_change(
        brand,
        what="Extract the guidelines' claims",
        why="Every claim is checked against its quote",
        evidence=evidence or [Evidence(file="theme/ingest/topics.json")],
        before=[],
        after=[],
        formats=["slides", "doc"],
    )
    print(f"{len(result.claims)} claims kept, {len(result.dropped)} dropped")
    print(f"{len(questions)} illustrative claims")
    for topic in topic_groups(topics):
        print(f"{topic}  {sum(claim.topic == topic for claim in result.claims)}")
    return 0


def _segment(brand: Path) -> int:
    if not segment_needed(brand):
        print("topics up to date")
        return 0
    begin_change(brand, "segment")
    topics = asyncio.run(segment_pages(brand, agents.brand_claude(brand)))
    record_change(
        brand,
        what="Sort the guidelines' pages into topics",
        why="Extraction reads each topic's pages together",
        evidence=[
            Evidence(file=entry.file, note=f"{len(entry.pages) + len(entry.missing)} pages") for entry in topics.files
        ],
        before=[],
        after=[],
        formats=["slides", "doc"],
    )
    for topic, pages in topic_groups(topics).items():
        print(f"{topic}  {len(pages)} pages")
    print(f"{sum(len(entry.missing) for entry in topics.files)} pages without a topic")
    return 0


def _templates(brand: Path) -> int:
    from docla.brand.templates import read_templates

    manifest = load_manifest(brand)
    if not any(e.type in ("pptx", "potx", "docx", "dotx") and e.unread is None for e in manifest.files):
        print("no readable PowerPoint templates")
        return 2
    branch = begin_change(brand, "templates")
    report = read_templates(brand)
    if not report.templates:
        # Nothing could be read: abandon the change so the brand is back on main, unchanged.
        run_git(brand, "reset", "-q", "--hard")
        run_git(brand, "clean", "-fdq")
        run_git(brand, "checkout", "-q", "main")
        run_git(brand, "branch", "-q", "-D", branch)
        for item in report.unread:
            print(f"{item.file}  unread: {item.reason}")
        print("no readable PowerPoint templates")
        return 2
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


def _set(brand: Path, args: argparse.Namespace) -> int:
    value = yaml.safe_load(args.value)
    proposal = _proposal(brand, args.path, value, args.reason)
    if proposal and not args.approve:
        source = proposal.source.source
        print(f"{proposal.path}: {proposal.source_value} -> {proposal.value}")
        print(f"Source: {source.file or ', '.join(source.files)} page {source.page}")
        print("not recorded: departs from the brand's sources; add --approve to record it")
        return 2
    if proposal and not args.reason.strip():
        raise BrandError(f"A reason is required for departure: {args.path}")
    begin_change(brand, "set-" + re.sub(r"[^a-z0-9]+", "-", args.path.lower()).strip("-")[:36])
    departure = set_token(
        brand,
        args.path,
        value,
        provenance=ValueProvenance(label="answered", source=ValueSource(question="cli", note=args.reason)),
        reason=args.reason,
        person="owner",
        approved=args.approve,
    )
    evidence = [Evidence(file="theme/tokens.yaml", note=args.path)]
    if departure:
        source = departure.source.source
        files = ([source.file] if source.file else []) + source.files
        evidence.extend(Evidence(file=file, page=source.page) for file in files)
    record_change(
        brand,
        what=f"Set {args.path} to {value}",
        why=args.reason,
        evidence=evidence,
        before=[],
        after=[],
        formats=[departure.format] if departure and departure.format else ["slides", "doc"],
    )
    return 0


def _role_page(value: str) -> tuple[str, int]:
    try:
        file, page = value.rsplit(":", 1)
        if not file:
            raise ValueError
        return file, int(page)
    except ValueError as error:
        raise BrandError(f"Invalid page argument: {value}") from error


def _roles(brand: Path, args: argparse.Namespace) -> int:
    if not args.map and not args.unmap:
        mappings = load_roles(brand).mappings
        for item in mappings:
            print(f"{item.file} p{item.page}  {item.component}  {item.format}")
        if not mappings:
            print("no mappings")
        return 0
    mapped = []
    for value in args.map:
        if "=" not in value:
            raise BrandError(f"Invalid mapping argument: {value}")
        reference, component = value.rsplit("=", 1)
        file, page = _role_page(reference)
        if not component:
            raise BrandError(f"Invalid mapping argument: {value}")
        mapped.append((file, page, component))
    unmapped = [_role_page(value) for value in args.unmap]
    record_roles(brand, mapped, unmapped, note=args.note)
    print(f"{len(load_roles(brand).mappings)} mappings")
    return 0


def run_brand(args: argparse.Namespace) -> int:
    try:
        if args.brand_command == "init":
            print(init_brand(args.slug, args.root))
        elif args.brand_command == "intake":
            return _intake(brand_path(args.slug, args.root))
        elif args.brand_command == "parse":
            return _parse(brand_path(args.slug, args.root))
        elif args.brand_command == "roles":
            return _roles(brand_path(args.slug, args.root), args)
        elif args.brand_command == "segment":
            return _segment(brand_path(args.slug, args.root))
        elif args.brand_command == "extract":
            return _extract(brand_path(args.slug, args.root))
        elif args.brand_command == "tie":
            return _tie(brand_path(args.slug, args.root))
        elif args.brand_command == "fonts":
            return _fonts(brand_path(args.slug, args.root))
        elif args.brand_command == "gaps":
            return _gaps(brand_path(args.slug, args.root))
        elif args.brand_command == "templates":
            return _templates(brand_path(args.slug, args.root))
        elif args.brand_command == "set":
            return _set(brand_path(args.slug, args.root), args)
        elif args.brand_command == "reconcile":
            return _reconcile(brand_path(args.slug, args.root))
        elif args.brand_command == "measure":
            return _measure(brand_path(args.slug, args.root))
        elif args.brand_command == "synthesise":
            return _synthesise(brand_path(args.slug, args.root))
        else:
            records = change_log(brand_path(args.slug, args.root))
            for record in records:
                print(f"{record.id}  {record.created[:10]}  {record.what}")
            if not records:
                print("no changes")
    except (BrandError, GitError, ThemeError, yaml.YAMLError) as error:
        print(error, file=sys.stderr)
        return 2
    return 0
