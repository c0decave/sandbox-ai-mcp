#!/usr/bin/env python3
"""The conversion child of the markitdown server (sandbox-ai-mcp): one document in, its Markdown out.

server.py starts this program once per conversion with the checked file as its standard input (the descriptor the
server opened, never a path) and the file's extension as the only argument. It limits itself before it imports
anything of markitdown (address space, CPU time, no file written, few descriptors), converts with markitdown 0.1.9's
own converters for text, HTML, CSV, Jupyter notebooks, RSS/Atom, DOCX (mammoth) and EPUB, with pdfminer.six for PDF
and with the two small converters below for XLSX and PPTX (standard library and defusedxml; markitdown's own need
pandas and python-pptx with lxml and Pillow, which are not in this image), and writes the Markdown to standard
output. Nothing is fetched: markitdown's URL converters (Wikipedia, YouTube, Bing), its image, audio, Azure and
plugin paths are never registered, and the image has no network.

Exit status: 0 the Markdown on stdout; 2 a format no converter takes; 3 the conversion failed; 4 a limit was hit.
The reason is one line on stderr, without the file's path or contents.
"""

from __future__ import annotations

import datetime as dt
import io
import os
import posixpath
import re
import resource
import sys
import types
import zipfile

MAX_INPUT_BYTES = 64 << 20          # the server refuses larger files before starting this
MAX_MEMORY = 1536 << 20             # address space of this process
CPU_SECONDS = 150                   # the server's wall-clock limit is shorter; this one stops a busy loop anyway
MAX_ZIP_ENTRIES = 20_000            # DOCX/XLSX/PPTX/EPUB are ZIP files: at most this many entries
MAX_ZIP_TOTAL = 384 << 20           # ... this much uncompressed in all
MAX_ZIP_RATIO = 200                 # ... and no entry more than this many times its compressed size (zip bombs)
MAX_CELLS = 2_000_000               # XLSX: cells read in all
MAX_COLUMNS = 512                   # XLSX: columns of a sheet shown


class Limit(Exception):
    """A limit of this program was reached; the text says which."""


def limit_self() -> None:
    for which, value in ((resource.RLIMIT_AS, MAX_MEMORY), (resource.RLIMIT_CPU, CPU_SECONDS),
                         (resource.RLIMIT_FSIZE, 0), (resource.RLIMIT_NOFILE, 64), (resource.RLIMIT_CORE, 0)):
        try:
            resource.setrlimit(which, (value, value))
        except (ValueError, OSError):
            pass


class _NoMagika:
    """Stands in for magika.Magika: markitdown 0.1.9 imports magika (Google's ONNX file-type model, on onnxruntime
    and numpy) and asks it for every stream; an answer whose status is not "ok" leaves markitdown with the guess from
    the file's extension, which is all this server gives it (see PROVENANCE.md)."""

    def identify_stream(self, stream):  # noqa: D401 - markitdown's call
        return types.SimpleNamespace(status="not_available")

    def identify_bytes(self, data):
        return types.SimpleNamespace(status="not_available")


sys.modules["magika"] = types.SimpleNamespace(Magika=_NoMagika)


# --- ZIP containers ---------------------------------------------------------------------------------------------------

def check_zip(data: bytes) -> None:
    """Limit a ZIP container before a converter reads it: entries, total size, compression ratio."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
    except (zipfile.BadZipFile, ValueError, OSError):
        return  # not a ZIP file: the converter says so
    if len(entries) > MAX_ZIP_ENTRIES:
        raise Limit(f"the file has more than {MAX_ZIP_ENTRIES} parts")
    total = 0
    for entry in entries:
        total += entry.file_size
        if entry.file_size > 1 << 20 and entry.file_size > MAX_ZIP_RATIO * max(entry.compress_size, 1):
            raise Limit("a part of the file is compressed more than 200:1 (a zip bomb?)")
    if total > MAX_ZIP_TOTAL:
        raise Limit(f"the file unpacks to more than {MAX_ZIP_TOTAL >> 20} MiB")


def _xml(archive: zipfile.ZipFile, name: str):
    """The root element of the XML part NAME (defusedxml: no DTD, no entities), or None when there is none."""
    from defusedxml import ElementTree
    try:
        data = archive.read(name)
    except KeyError:
        return None
    return ElementTree.fromstring(data, forbid_dtd=True)


def _rels(archive: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    """Relationship id -> (type, the target's part name) of PART."""
    folder, name = posixpath.split(part)
    root = _xml(archive, posixpath.join(folder, "_rels", name + ".rels"))
    out = {}
    if root is None:
        return out
    for rel in root:
        target = rel.get("Target") or ""
        if rel.get("TargetMode") == "External":
            continue
        path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
        out[rel.get("Id") or ""] = (rel.get("Type") or "", path)
    return out


def _cell_text(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def _table(rows: list[list[str]]) -> str:
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows[1:]]
    return "\n".join(lines)


# --- XLSX -------------------------------------------------------------------------------------------------------------

S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_DATE_FORMATS = set(range(14, 23)) | {45, 46, 47}
_CELL_REF = re.compile(r"^([A-Z]{1,3})(\d+)$")


def _column(ref: str) -> int | None:
    match = _CELL_REF.match(ref or "")
    if not match:
        return None
    number = 0
    for letter in match.group(1):
        number = number * 26 + ord(letter) - 64
    return number - 1


def _is_date_format(code: str) -> bool:
    code = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", code.lower())
    return bool(re.search(r"[dy]", code)) or bool(re.search(r"(^|[^a-z])m+([^a-z]|$)", code) and "h" not in code)


def _excel_date(value: str, date1904: bool) -> str:
    try:
        number = float(value)
    except ValueError:
        return value
    if not 0 <= number < 2958466:
        return value
    base = dt.datetime(1904, 1, 1) if date1904 else dt.datetime(1899, 12, 30)
    moment = base + dt.timedelta(days=number)
    if moment.hour == moment.minute == moment.second == 0 and number == int(number):
        return moment.date().isoformat()
    return moment.replace(microsecond=0).isoformat(sep=" ")


def _number(value: str) -> str:
    try:
        number = float(value)
    except ValueError:
        return value
    if number.is_integer() and abs(number) < 1e15:
        return str(int(number))
    return repr(number)


def xlsx_to_markdown(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        workbook = _xml(archive, "xl/workbook.xml")
        if workbook is None:
            raise ValueError("not an XLSX workbook (no xl/workbook.xml)")
        date1904 = any(p.get("date1904") in ("1", "true") for p in workbook.iter(S + "workbookPr"))
        shared: list[str] = []
        strings = _xml(archive, "xl/sharedStrings.xml")
        if strings is not None:
            for item in strings.iter(S + "si"):
                shared.append("".join(t.text or "" for t in item.iter(S + "t")))
        date_styles: set[int] = set()
        styles = _xml(archive, "xl/styles.xml")
        if styles is not None:
            custom = {int(f.get("numFmtId", "-1")): f.get("formatCode", "") for f in styles.iter(S + "numFmt")}
            xfs = styles.find(S + "cellXfs")
            for index, xf in enumerate(xfs if xfs is not None else []):
                fmt = int(xf.get("numFmtId", "0"))
                if fmt in _DATE_FORMATS or (fmt in custom and _is_date_format(custom[fmt])):
                    date_styles.add(index)
        rels = _rels(archive, "xl/workbook.xml")
        out, cells = [], 0
        for sheet in workbook.iter(S + "sheet"):
            name = sheet.get("name") or "Sheet"
            target = rels.get(sheet.get(R + "id") or "")
            if target is None:
                continue
            root = _xml(archive, target[1])
            if root is None:
                continue
            rows: list[list[str]] = []
            cut = False
            for row in root.iter(S + "row"):
                values: dict[int, str] = {}
                for position, cell in enumerate(row.iter(S + "c")):
                    cells += 1
                    if cells > MAX_CELLS:
                        raise Limit(f"the workbook has more than {MAX_CELLS} cells")
                    column = _column(cell.get("r") or "")
                    column = position if column is None else column
                    if column >= MAX_COLUMNS:
                        cut = True
                        continue
                    kind = cell.get("t") or "n"
                    raw = cell.find(S + "v")
                    text = raw.text if raw is not None and raw.text is not None else ""
                    if kind == "s":
                        try:
                            text = shared[int(text)]
                        except (ValueError, IndexError):
                            text = ""
                    elif kind == "inlineStr":
                        text = "".join(t.text or "" for t in cell.iter(S + "t"))
                    elif kind == "b":
                        text = "TRUE" if text == "1" else "FALSE"
                    elif kind == "n" and text:
                        style = int(cell.get("s") or "0")
                        text = _excel_date(text, date1904) if style in date_styles else _number(text)
                    values[column] = _cell_text(text)
                if values:  # (empty rows are left out)
                    width = max(values) + 1
                    rows.append([values.get(i, "") for i in range(width)])
            out.append(f"## {_cell_text(name)}")
            out.append(_table(rows) if rows else "(empty sheet)")
            if cut:
                out.append(f"(only the first {MAX_COLUMNS} columns are shown)")
        return "\n\n".join(out)


# --- PPTX -------------------------------------------------------------------------------------------------------------

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"


def _paragraphs(element) -> list[str]:
    out = []
    for paragraph in element.iter(A + "p"):
        text = "".join(run.text or "" for run in paragraph.iter(A + "t")).strip()
        if text:
            out.append(text)
    return out


def _shape_kind(shape) -> str:
    for ph in shape.iter(P + "ph"):
        return ph.get("type") or "body"
    return ""


def _slide_items(tree) -> list[str]:
    """Text of a slide's shapes in their order: the title as a heading, tables as Markdown tables."""
    out = []
    for shape in tree:
        tag = shape.tag
        if tag == P + "grpSp":
            out += _slide_items(shape)
        elif tag == P + "sp":
            body = shape.find(P + "txBody")
            if body is None:
                continue
            lines = _paragraphs(body)
            if not lines:
                continue
            if _shape_kind(shape) in ("title", "ctrTitle"):
                out.append("# " + " ".join(lines))
            else:
                out.append("\n".join(lines))
        elif tag == P + "graphicFrame":
            for table in shape.iter(A + "tbl"):
                rows = [[_cell_text(" ".join(_paragraphs(cell))) for cell in row.iter(A + "tc")]
                        for row in table.iter(A + "tr")]
                rows = [row for row in rows if row]
                if rows:
                    out.append(_table(rows))
    return out


def pptx_to_markdown(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        presentation = _xml(archive, "ppt/presentation.xml")
        if presentation is None:
            raise ValueError("not a PPTX presentation (no ppt/presentation.xml)")
        rels = _rels(archive, "ppt/presentation.xml")
        out = []
        for number, slide_id in enumerate(presentation.iter(P + "sldId"), start=1):
            target = rels.get(slide_id.get(R + "id") or "")
            if target is None:
                continue
            slide = _xml(archive, target[1])
            if slide is None:
                continue
            tree = slide.find(f"{P}cSld/{P}spTree")
            parts = [f"<!-- Slide number: {number} -->"] + (_slide_items(tree) if tree is not None else [])
            for kind, notes_part in _rels(archive, target[1]).values():
                if kind.endswith("/notesSlide"):
                    notes = _xml(archive, notes_part)
                    tree = notes.find(f"{P}cSld/{P}spTree") if notes is not None else None
                    lines = []
                    for shape in (tree if tree is not None else []):
                        if shape.tag == P + "sp" and _shape_kind(shape) == "body":
                            body = shape.find(P + "txBody")
                            lines += _paragraphs(body) if body is not None else []
                    if lines:
                        parts.append("### Notes:\n" + "\n".join(lines))
            out.append("\n\n".join(parts))
        return "\n\n".join(out)


# --- markitdown ------------------------------------------------------------------------------------------------------

def converters():
    """markitdown's converters this server uses, and its own for PDF (pdfminer.six alone), XLSX and PPTX."""
    from markitdown import DocumentConverter, DocumentConverterResult, PRIORITY_GENERIC_FILE_FORMAT
    from markitdown.converters import (CsvConverter, DocxConverter, EpubConverter, HtmlConverter, IpynbConverter,
                                       PlainTextConverter, RssConverter)
    from markitdown.converters._pdf_converter import _merge_partial_numbering_lines

    class Pdf(DocumentConverter):
        """markitdown's PDF path without pdfplumber (its form/table pass needs pypdfium2 and Pillow): the text of
        every page through pdfminer.six's extract_text, then markitdown's own merge of partial numbering."""

        def accepts(self, file_stream, stream_info, **kwargs):
            return (stream_info.extension or "").lower() == ".pdf" \
                or (stream_info.mimetype or "").lower().startswith(("application/pdf", "application/x-pdf"))

        def convert(self, file_stream, stream_info, **kwargs):
            import pdfminer.high_level
            text = pdfminer.high_level.extract_text(io.BytesIO(file_stream.read()))
            return DocumentConverterResult(markdown=_merge_partial_numbering_lines(text))

    class Zipped(DocumentConverter):
        def __init__(self, extension: str, mimetype: str, convert):
            super().__init__()
            self._extension, self._mimetype, self._convert = extension, mimetype, convert

        def accepts(self, file_stream, stream_info, **kwargs):
            return (stream_info.extension or "").lower() == self._extension \
                or (stream_info.mimetype or "").lower().startswith(self._mimetype)

        def convert(self, file_stream, stream_info, **kwargs):
            return DocumentConverterResult(markdown=self._convert(file_stream.read()))

    generic = [PlainTextConverter(), HtmlConverter()]
    specific = [RssConverter(), IpynbConverter(), DocxConverter(), EpubConverter(), CsvConverter(), Pdf(),
                Zipped(".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml", xlsx_to_markdown),
                Zipped(".pptx", "application/vnd.openxmlformats-officedocument.presentationml", pptx_to_markdown)]
    return generic, specific, PRIORITY_GENERIC_FILE_FORMAT


def looks_like_text(data: bytes) -> str | None:
    """'utf-8' when DATA's start decodes as UTF-8 without NUL bytes (a text file of an extension markitdown does not
    know, e.g. .log or .ini); magika would have said "text" for it."""
    sample = data[:65536]
    if b"\x00" in sample:
        return None
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError as exc:
        if exc.start < len(sample) - 4:  # a character cut at the sample's end is fine
            return None
    return "utf-8"


def convert(data: bytes, extension: str) -> str:
    from markitdown import MarkItDown, StreamInfo, UnsupportedFormatException
    generic, specific, generic_priority = converters()
    engine = MarkItDown(enable_builtins=False, enable_plugins=False)
    for converter in generic:
        engine.register_converter(converter, priority=generic_priority)
    for converter in specific:
        engine.register_converter(converter)
    if extension in (".docx", ".xlsx", ".pptx", ".epub"):
        check_zip(data)
    info = StreamInfo(extension=extension or None, filename="document" + extension)
    try:
        return engine.convert_stream(io.BytesIO(data), stream_info=info).markdown
    except UnsupportedFormatException:
        charset = looks_like_text(data)
        if charset is None:
            raise
        return engine.convert_stream(io.BytesIO(data), stream_info=StreamInfo(extension=".txt",
                                                                              charset=charset)).markdown


def main(argv: list[str]) -> int:
    limit_self()
    extension = argv[1].lower() if len(argv) > 1 else ""
    if not re.fullmatch(r"(\.[a-z0-9]{1,10})?", extension):
        extension = ""
    try:
        data = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(data) > MAX_INPUT_BYTES:
            raise Limit(f"the file is larger than {MAX_INPUT_BYTES >> 20} MiB")
        markdown = convert(data, extension)
    except Limit as exc:
        print(str(exc), file=sys.stderr)
        return 4
    except MemoryError:
        print(f"the conversion needed more than {MAX_MEMORY >> 20} MiB of memory", file=sys.stderr)
        return 4
    except RecursionError:
        print("the document is nested too deeply", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 - reported by kind, never with the file's text
        from markitdown import FileConversionException, UnsupportedFormatException
        if isinstance(exc, UnsupportedFormatException):
            print("no converter takes this kind of file", file=sys.stderr)
            return 2
        if isinstance(exc, FileConversionException) and exc.attempts:
            inner = exc.attempts[0].exc_info
            kind = inner[0].__name__ if inner and inner[0] else type(exc).__name__
        else:
            kind = type(exc).__name__
        print(f"the conversion failed ({kind})", file=sys.stderr)
        return 3
    out = sys.stdout.buffer
    out.write(markdown.encode("utf-8", "replace"))
    out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
