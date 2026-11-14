"""Read structural facts from PowerPoint templates."""

import hashlib
import io
import zipfile
from pathlib import Path
from typing import Any, Literal

from pptx import Presentation
from pptx.enum.dml import MSO_COLOR_TYPE, MSO_FILL
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml import parse_xml
from pydantic import BaseModel

from docla.brand.pages import load_manifest
from docla.model.source import Format


class TemplateBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class PageModel(BaseModel):
    width: float
    height: float
    margins: list[float] | None = None
    columns: int | None = None
    column_gap: float | None = None


class TemplateColour(BaseModel):
    role: str
    hex: str
    where: str


class TemplateFont(BaseModel):
    role: str
    family: str
    where: str


class StyleFact(BaseModel):
    name: str
    kind: Literal["text-level", "paragraph", "character", "table"]
    based_on: str | None = None
    font: str | None
    size: float | None
    bold: bool | None
    italic: bool | None
    colour: str | None
    theme_colour: str | None
    where: str


class PlaceholderFact(BaseModel):
    type: str
    idx: int
    name: str
    box: TemplateBox | None


class ShapeFact(BaseModel):
    name: str
    kind: Literal["picture", "shape", "line", "group", "other"]
    box: TemplateBox | None
    fill: str | None
    text: str | None
    placeholder: str | None


class LayoutFact(BaseModel):
    name: str
    master: int
    placeholders: list[PlaceholderFact]
    decorations: list[ShapeFact]
    where: str


class SlideFact(BaseModel):
    number: int
    layout: str
    hidden: bool
    shapes: list[ShapeFact]


class MediaFact(BaseModel):
    part: str
    sha256: str
    size: int


class TemplateFacts(BaseModel):
    schema_version: int = 1
    source: str
    sha256: str
    kind: Literal["pptx", "docx"]
    format: Format
    page_model: PageModel
    colours: list[TemplateColour]
    fonts: list[TemplateFont]
    styles: list[StyleFact]
    layouts: list[LayoutFact]
    master_shapes: list[ShapeFact]
    slides: list[SlideFact]
    media: list[MediaFact]
    warnings: list[str]


class UnreadTemplate(BaseModel):
    file: str
    reason: str


class TemplateReport(BaseModel):
    schema_version: int = 1
    templates: list[TemplateFacts]
    unread: list[UnreadTemplate]


class TemplateError(ValueError):
    """A template archive cannot be read safely."""


def check_zip(path: Path) -> list[str]:
    warnings = []
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 10000 or sum(e.file_size for e in entries) > 512 * 1024 * 1024:
                raise TemplateError("Template archive exceeds size limits")
            for entry in entries:
                if entry.file_size > 1024 * 1024 and entry.file_size > 200 * entry.compress_size:
                    raise TemplateError(f"Template archive entry exceeds compression limit: {entry.filename}")
                if entry.filename.endswith(".rels"):
                    root = parse_xml(archive.read(entry))
                    for rel in root:
                        if rel.get("TargetMode") == "External":
                            warnings.append(f"external link in {entry.filename}: {rel.get('Target')}")
    except zipfile.BadZipFile as error:
        raise TemplateError(f"Not a zip archive: {path}") from error
    return warnings


def _part(part: Any) -> str:
    return str(part.partname).lstrip("/")


def _theme(master: Any, warnings: list[str]) -> tuple[list[TemplateColour], list[TemplateFont]]:
    part = master.part.part_related_by(RT.THEME)
    root = parse_xml(part.blob)
    location = _part(part)
    colours: list[TemplateColour] = []
    for scheme in root.xpath(".//a:clrScheme"):
        for item in scheme:
            role = item.tag.split("}")[-1]
            _colour(item, role, f"{location}#clrScheme/{role}", colours, warnings)
    for item in root.xpath(".//a:custClrLst/a:custClr"):
        role = f"custom.{item.get('name')}"
        _colour(item, role, f"{location}#custClrLst/{role}", colours, warnings)
    fonts = []
    for role in ("major", "minor"):
        nodes = root.xpath(f".//a:{role}Font/a:latin")
        if nodes and nodes[0].get("typeface"):
            fonts.append(TemplateFont(role=role, family=nodes[0].get("typeface"), where=f"{location}#{role}Font/latin"))
    return colours, fonts


def _colour(item: Any, role: str, where: str, colours: list[TemplateColour], warnings: list[str]) -> None:
    node = item[0] if len(item) else None
    tag = node.tag.split("}")[-1] if node is not None else ""
    value = (
        node.get("val" if tag == "srgbClr" else "lastClr")
        if node is not None and tag in ("srgbClr", "sysClr")
        else None
    )
    if value:
        colours.append(TemplateColour(role=role, hex=f"#{value.upper()}", where=where))
    else:
        warnings.append(f"unsupported colour in {where}")


def _styles(master: Any, fonts: list[TemplateFont]) -> list[StyleFact]:
    families = {f.role: f.family for f in fonts}
    result = []
    for name, style, level in [("title", "titleStyle", 1)] + [(f"body.{i}", "bodyStyle", i) for i in range(1, 4)]:
        nodes = master._element.xpath(f"./p:txStyles/p:{style}/a:lvl{level}pPr/a:defRPr")
        if not nodes:
            continue
        node = nodes[0]
        latin = node.xpath("./a:latin")
        font = latin[0].get("typeface") if latin else None
        if font is not None:
            font = {"+mj-lt": families.get("major"), "+mn-lt": families.get("minor")}.get(font, font)
        rgb = node.xpath("./a:solidFill/a:srgbClr")
        scheme = node.xpath("./a:solidFill/a:schemeClr")
        result.append(
            StyleFact(
                name=name,
                kind="text-level",
                font=font,
                size=int(node.get("sz")) / 100 if node.get("sz") is not None else None,
                bold=_boolean(node.get("b")),
                italic=_boolean(node.get("i")),
                colour=f"#{rgb[0].get('val').upper()}" if rgb else None,
                theme_colour=scheme[0].get("val") if scheme else None,
                where=f"{_part(master.part)}#txStyles/{style}/lvl{level}pPr/defRPr",
            )
        )
    return result


def _boolean(value: str | None) -> bool | None:
    return None if value is None else value in ("1", "true", "on")


def _box(shape: Any) -> TemplateBox | None:
    x, y, w, h = shape.left, shape.top, shape.width, shape.height
    if any(v is None for v in (x, y, w, h)):
        return None
    return TemplateBox(x0=x / 12700, y0=y / 12700, x1=(x + w) / 12700, y1=(y + h) / 12700)


def _placeholder(shape: Any) -> str:
    return str(shape.placeholder_format.type.name).lower()


def _shape(shape: Any) -> ShapeFact:
    kinds: dict[Any, Literal["picture", "shape", "line", "group", "other"]] = {
        MSO_SHAPE_TYPE.PICTURE: "picture",
        MSO_SHAPE_TYPE.AUTO_SHAPE: "shape",
        MSO_SHAPE_TYPE.LINE: "line",
        MSO_SHAPE_TYPE.GROUP: "group",
        MSO_SHAPE_TYPE.TEXT_BOX: "shape",
    }
    fill = None
    if hasattr(shape, "fill") and shape.fill.type == MSO_FILL.SOLID:
        colour = shape.fill.fore_color
        if colour.type == MSO_COLOR_TYPE.RGB:
            fill = f"#{colour.rgb}"
    return ShapeFact(
        name=shape.name,
        kind=kinds.get(shape.shape_type, "other"),
        box=_box(shape),
        fill=fill,
        text=shape.text if shape.has_text_frame else None,
        placeholder=_placeholder(shape) if shape.is_placeholder else None,
    )


def _layout(layout: Any, number: int) -> LayoutFact:
    placeholders = [
        PlaceholderFact(type=_placeholder(s), idx=s.placeholder_format.idx, name=s.name, box=_box(s))
        for s in layout.placeholders
    ]
    return LayoutFact(
        name=layout.name,
        master=number,
        placeholders=placeholders,
        decorations=[_shape(s) for s in layout.shapes if not s.is_placeholder],
        where=_part(layout.part),
    )


def _presentation(data: bytes) -> Any:
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(output, "w") as target:
        for item in source.infolist():
            content = source.read(item)
            if item.filename == "[Content_Types].xml":
                content = content.replace(b"presentationml.template.main+xml", b"presentationml.presentation.main+xml")
            target.writestr(item, content)
    output.seek(0)
    return Presentation(output)


def read_pptx(path: Path, source: str) -> TemplateFacts:
    warnings = check_zip(path)
    data = path.read_bytes()
    presentation = _presentation(data)
    masters = list(presentation.slide_masters)
    colours, fonts = _theme(masters[0], warnings)
    slides = []
    for number, slide in enumerate(presentation.slides, 1):
        hidden = slide._element.get("show") == "0"
        if hidden:
            warnings.append(f"slide {number} is hidden")
        slides.append(
            SlideFact(
                number=number,
                layout=slide.slide_layout.name,
                hidden=hidden,
                shapes=[_shape(shape) for shape in slide.shapes],
            )
        )
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        media = []
        for name in sorted(n for n in archive.namelist() if n.startswith("ppt/media/") and not n.endswith("/")):
            blob = archive.read(name)
            media.append(MediaFact(part=name, sha256=hashlib.sha256(blob).hexdigest(), size=len(blob)))
    return TemplateFacts(
        source=source,
        sha256=hashlib.sha256(data).hexdigest(),
        kind="pptx",
        format="slides",
        page_model=PageModel(width=presentation.slide_width / 12700, height=presentation.slide_height / 12700),
        colours=colours,
        fonts=fonts,
        styles=_styles(masters[0], fonts),
        layouts=[_layout(layout, n) for n, master in enumerate(masters, 1) for layout in master.slide_layouts],
        master_shapes=[_shape(s) for master in masters for s in master.shapes if not s.is_placeholder],
        slides=slides,
        media=media,
        warnings=warnings,
    )


def read_templates(brand: Path) -> TemplateReport:
    manifest = load_manifest(brand)
    templates = []
    unread = []
    for entry in sorted(manifest.files, key=lambda e: e.path):
        if entry.type in ("pptx", "potx") and entry.unread is None:
            try:
                templates.append(read_pptx(brand / entry.path, entry.path))
            except Exception as error:
                unread.append(UnreadTemplate(file=entry.path, reason=str(error) or type(error).__name__))
    report = TemplateReport(templates=templates, unread=unread)
    destination = brand / "theme/ingest/templates.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return report
