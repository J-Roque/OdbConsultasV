"""Normaliza la consulta publica de infracciones de la ATU (Lima y Callao).

La pasarela de pagos de la ATU (SPA con reCAPTCHA v3 invisible) cifra las
respuestas de su API, asi que el conector no la lee: toma lo que la pagina
muestra al usuario. Este modulo recibe esa "foto" de la pagina y la convierte
en el contrato, sin inventar datos.

Foto esperada (``snapshot``)::

    {
      "modal": "texto del aviso (sin titulo ni boton) o None",
      "icon": "info" | "error" | "warning" | "success" | None,
      "head": ["Ver Acta", "Seleccionar", "Placa", ...],
      "rows": [["", "", "ABC123", ...], ...],
      "counter": "Registros 1 - 3 de 3",
    }
"""
from __future__ import annotations

import re
import unicodedata

from obd_consultas.domain.models import QueryResult, QueryStatus, Source, normalize_plate
from obd_consultas.providers.catalog import SOURCES

ATU_INFO = next(info for info in SOURCES if info.source == Source.ATU)
ATU_FORM_URL = "https://pasarela.atu.gob.pe/"
# Columnas de accion (botones), sin dato.
_SKIP_COLUMNS = {"ver_acta", "seleccionar"}
_NO_INFRACTION = re.compile(r"no cuenta con infracci", re.IGNORECASE)
_CAPTCHA = re.compile(r"captcha|robot|verificaci", re.IGNORECASE)
_COUNTER = re.compile(r"de\s+(\d+)\s*$", re.IGNORECASE)
_EMPTY_ROW = "sin registros"


class AtuParseError(ValueError):
    pass


def column_key(title: str) -> str:
    """``"Acta Fiscalización"`` -> ``"acta_fiscalizacion"``."""
    plain = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", plain.lower()).strip("_")


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _total(counter: object) -> int | None:
    match = _COUNTER.search(_clean(counter))
    return int(match.group(1)) if match else None


def parse_rows(head: list[object], rows: list[list[object]], plate: str) -> list[dict[str, str]]:
    keys = [column_key(_clean(title)) for title in head]
    if "placa" not in keys:
        raise AtuParseError("La tabla de la ATU no tiene la columna Placa.")
    infracciones = []
    for row in rows:
        cells = [_clean(cell) for cell in row]
        if len(cells) == 1 and cells[0].lower() == _EMPTY_ROW:
            continue
        if len(cells) != len(keys):
            raise AtuParseError("Fila de la ATU con un numero de columnas inesperado.")
        campos = {
            key: value
            for key, value in zip(keys, cells, strict=True)
            if key and key not in _SKIP_COLUMNS and value
        }
        if normalize_plate(campos.get("placa", "")) != plate:
            raise AtuParseError("La tabla de la ATU corresponde a otra placa.")
        infracciones.append(campos)
    return infracciones


def atu_result(
    plate: str, status: QueryStatus, message: str, data: dict | None = None
) -> QueryResult:
    return QueryResult(Source.ATU, plate, status, ATU_INFO.url, message, data or {})


def result_from_snapshot(plate: str, snapshot: dict[str, object]) -> QueryResult:
    plate = normalize_plate(plate)
    modal = _clean(snapshot.get("modal")) or None
    icon = snapshot.get("icon")
    head = snapshot.get("head") or []
    rows = snapshot.get("rows") or []
    if not isinstance(head, list) or not isinstance(rows, list):
        return atu_result(plate, QueryStatus.PARSE_ERROR, "La tabla de la ATU tiene un formato inesperado.")

    try:
        infracciones = parse_rows(head, [r for r in rows if isinstance(r, list)], plate) if rows else []
    except AtuParseError as exc:
        return atu_result(plate, QueryStatus.PARSE_ERROR, str(exc))

    if infracciones:
        total = _total(snapshot.get("counter"))
        data = {
            "tiene_infracciones": True,
            "infracciones": infracciones,
            "total_registros": total if total is not None else len(infracciones),
            # La tabla pagina de 10 en 10; solo se lee la primera pagina.
            "completo": total is None or total <= len(infracciones),
            "mensaje": None,
        }
        return atu_result(plate, QueryStatus.SUCCESS, "Consulta obtenida de la pasarela ATU.", data)

    if modal and _NO_INFRACTION.search(modal):
        data = {
            "tiene_infracciones": False,
            "infracciones": [],
            "total_registros": 0,
            "completo": True,
            "mensaje": modal,
        }
        return atu_result(plate, QueryStatus.NOT_FOUND, "La ATU no registra infracciones para esta placa.", data)

    if modal and _CAPTCHA.search(modal):
        return atu_result(
            plate,
            QueryStatus.REQUIRES_INTERACTION,
            "La ATU rechazo la verificacion reCAPTCHA de la consulta. Prueba de nuevo en unos minutos.",
        )
    if modal and icon in {"error", "warning"}:
        return atu_result(plate, QueryStatus.UNAVAILABLE, f"La ATU respondio: {modal[:200]}")
    if modal:
        return atu_result(plate, QueryStatus.PARSE_ERROR, f"Aviso de la ATU no reconocido: {modal[:200]}")
    return atu_result(
        plate,
        QueryStatus.REQUIRES_INTERACTION,
        "La ATU no mostro resultado a tiempo. Prueba de nuevo en unos minutos.",
    )


class AtuProvider:
    info = ATU_INFO

    def query(self, plate: str) -> QueryResult:
        return atu_result(
            normalize_plate(plate),
            QueryStatus.REQUIRES_INTERACTION,
            "La ATU exige reCAPTCHA en su pasarela. Usa --stealth (o /v1/queries/stealth): el navegador completa la consulta oficial.",
        )
