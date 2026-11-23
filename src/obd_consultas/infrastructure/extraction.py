
"""Extraccion declarativa reutilizable sobre el motor de Scrapling.

Los conectores describen que quieren leer con reglas pequenas en vez de repetir
CSS/XPath. Es el equivalente a los selectores de Scrapling, sin acoplarse a un
portal concreto. Sirve para SOAT DOM, SUNARP, MTC o cualquier tabla HTML.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Literal, Sequence

from obd_consultas.infrastructure.scrapling_engine import parse_html

Engine = Literal["css", "xpath"]
Mode = Literal["text", "all_text", "html", "attr", "url"]


class ExtractionError(ValueError):
    """La pagina no contiene los datos que la regla espera."""


@dataclass(frozen=True)
class Field:
    """Como leer un dato dentro de una fila.

    ``selector`` acepta pseudoelementos de Scrapy como ``a::attr(href)`` o
    ``.precio::text``. ``mode`` decide que se devuelve si el selector apunta a
    un nodo: su texto, su HTML, un atributo o una URL absoluta.
    """

    name: str
    selector: str
    engine: Engine = "css"
    mode: Mode = "text"
    attr: str | None = None
    pattern: str | None = None
    multiple: bool = False
    required: bool = True


def _as_selector(source: Any, url: str = "") -> Any:
    if isinstance(source, (str, bytes)):
        return parse_html(source, url=url)
    return source


def select(source: Any, selector: str, engine: Engine = "css", *, url: str = "") -> Any:
    """Devuelve los nodos que cumplen el selector (CSS por defecto)."""
    page = _as_selector(source, url)
    try:
        return page.css(selector) if engine == "css" else page.xpath(selector)
    except Exception as exc:  # SelectorSyntaxError y variantes
        raise ExtractionError(f"Selector invalido: {selector!r}") from exc


def _text_of(node: Any, separator: str) -> str | None:
    if getattr(node, "tag", "") == "#text":
        return str(node.get())
    return str(node.get_all_text(strip=True, separator=separator))


def _value_of(node: Any, field: Field) -> Any:
    if field.mode == "attr":
        if not field.attr:
            raise ExtractionError(f"El campo {field.name!r} necesita attr.")
        value = node.attrib.get(field.attr)
    elif field.mode == "url":
        attr = field.attr or "href"
        value = node.attrib.get(attr)
        if value:
            value = node.urljoin(value)
    elif field.mode == "html":
        value = str(node.html_content)
    elif field.mode == "all_text":
        value = _text_of(node, "\n")
    elif field.mode == "text":
        value = _text_of(node, " ")
    else:
        raise ExtractionError(f"Modo desconocido en {field.name!r}: {field.mode!r}")

    if value is not None and isinstance(value, str):
        if field.mode == "all_text":
            value = "\n".join(line.strip() for line in value.splitlines() if line.strip())
        elif field.mode != "html":
            value = " ".join(value.split())
    if value is not None and field.pattern and isinstance(value, str):
        match = re.search(field.pattern, value, re.S)
        value = (match.group(1) if match.groups() else match.group(0)) if match else None
    return value or None


def _field_value(row: Any, field: Field) -> Any:
    if not field.selector:
        return [_value_of(row, field)] if field.multiple else _value_of(row, field)
    nodes = select(row, field.selector, field.engine)
    if field.multiple:
        values = [_value_of(node, field) for node in nodes]
        return [value for value in values if value is not None]
    first = nodes.first
    return _value_of(first, field) if first is not None else None


def extract_rows(
    source: Any,
    row_selector: str,
    fields: Sequence[Field],
    *,
    engine: Engine = "css",
    require_rows: bool = True,
    url: str = "",
) -> list[dict[str, Any]]:
    """Aplica las mismas reglas a cada fila de una lista o tabla HTML.

    Lanza ``ExtractionError`` si no hay filas y ``require_rows`` esta activo, o
    si falta un campo obligatorio. Un portal vacio nunca se confunde con un
    fallo de lectura: eso lo decide el conector.
    """
    rows = select(source, row_selector, engine, url=url)
    if not rows:
        if require_rows:
            raise ExtractionError(f"No se encontraron filas con {row_selector!r}.")
        return []

    records: list[dict[str, Any]] = []
    for position, row in enumerate(rows, start=1):
        record: dict[str, Any] = {}
        for field in fields:
            value = _field_value(row, field)
            if value is None or value == [] or value == "":
                if field.required:
                    raise ExtractionError(
                        f"Fila {position}: falta el campo {field.name!r}."
                    )
                value = None
            record[field.name] = value
        records.append(record)
    return records


def extract_table(
    source: Any,
    table_selector: str = "table",
    *,
    header_row: int = 0,
    engine: Engine = "css",
    url: str = "",
) -> list[dict[str, str]]:
    """Convierte una tabla HTML en registros usando su fila de encabezados."""
    page = _as_selector(source, url)
    tables = select(page, table_selector, engine, url=url)
    table = tables.first if tables else None
    if table is None:
        raise ExtractionError(f"No se encontro la tabla {table_selector!r}.")

    rows = table.css("tr")
    if len(rows) <= header_row:
        raise ExtractionError("La tabla no tiene encabezados ni filas.")
    header = [
        " ".join(str(cell.get_all_text(strip=True)).split()).lower()
        for cell in rows[header_row].css("th, td")
    ]
    if not header or any(not name for name in header):
        raise ExtractionError("La tabla tiene encabezados vacios.")

    records: list[dict[str, str]] = []
    for row in rows[header_row + 1 :]:
        cells = [" ".join(str(cell.get_all_text(strip=True)).split()) for cell in row.css("td")]
        if not cells:
            continue
        records.append(dict(zip(header, cells)))
    return records


def to_text(
    source: Any,
    selector: str | None = None,
    *,
    engine: Engine = "css",
    url: str = "",
) -> str:
    """Texto limpio de la pagina completa o de los nodos indicados."""
    page = _as_selector(source, url)
    nodes = [page] if not selector else select(page, selector, engine, url=url)
    chunks = []
    for node in nodes:
        text = _text_of(node, "\n")
        if text:
            chunks.append(text.strip())
    return "\n\n".join(chunk for chunk in chunks if chunk)


def _clean_for_markdown(page: Any) -> Any:
    """Reutiliza la limpieza de Scrapling: quita ruido y contenido oculto."""
    try:
        from scrapling.core.shell import Convertor

        return Convertor._sanitize_for_ai(Convertor._strip_noise_tags(page))
    except Exception:  # pragma: no cover - detalle interno de Scrapling
        return page


def to_markdown(
    source: Any,
    selector: str | None = None,
    *,
    engine: Engine = "css",
    url: str = "",
    main_content_only: bool = False,
) -> str:
    """Convierte HTML en Markdown limpio, sin scripts ni estilos."""
    from markdownify import markdownify

    page = _as_selector(source, url)
    if main_content_only:
        page = page.css("body").first or page
    page = _clean_for_markdown(page)
    nodes = [page] if not selector else select(page, selector, engine, url=url)
    if not nodes:
        raise ExtractionError(f"El selector {selector!r} no devolvio contenido.")

    chunks = []
    for node in nodes:
        html = str(node) if getattr(node, "tag", "") == "#text" else str(node.html_content)
        converted = markdownify(
            html,
            heading_style="ATX",
            strip=["script", "style", "noscript"],
        )
        converted = converted.strip()
        if converted:
            chunks.append(converted)
    return "\n\n".join(chunks)


def selector_html(
    source: Any,
    selector: str | None = None,
    *,
    engine: Engine = "css",
    url: str = "",
) -> str:
    """HTML del nodo pedido o de la pagina completa."""
    page = _as_selector(source, url)
    if not selector:
        return str(page.html_content)
    nodes = select(page, selector, engine, url=url)
    return "\n".join(str(node.html_content) for node in nodes)
