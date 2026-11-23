"""Normaliza las consultas de revision tecnica del MTC.

El portal MTC usa un captcha de imagen que debe leer una persona: el conector no
lo resuelve ni lo elude. La consulta se ejecuta con el navegador visible y la
respuesta oficial se normaliza aqui.
"""
from __future__ import annotations

from datetime import datetime
import html
import json

from obd_consultas.domain.models import QueryResult, QueryStatus, Source, normalize_plate
from obd_consultas.providers.catalog import SOURCES

MTC_INFO = next(info for info in SOURCES if info.source == Source.MTC)
MTC_FORM_URL = MTC_INFO.url
LABELS = ("ULTIMO", "PENULTIMO", "ANTEPENULTIMO")


class MtcParseError(ValueError):
    pass


def _text(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise MtcParseError("Campo de texto con tipo inesperado.")
    return html.unescape(str(value)).strip() or None


def _date(value: object) -> str:
    raw = _text(value)
    if raw is None:
        raise MtcParseError("Falta una fecha de vigencia.")
    try:
        return datetime.strptime(raw, "%d/%m/%Y").date().isoformat()
    except ValueError as exc:
        raise MtcParseError("La fuente cambio el formato de fecha.") from exc


def _records(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise MtcParseError("La respuesta no incluye la lista de registros.")
    items: list[object] = list(value)
    # El portal entrega orResult[0] como un JSON que contiene TODOS los registros.
    # Tambien se acepta una lista de registros individuales (capturas sinteticas).
    if items:
        first = items[0]
        if isinstance(first, list):
            items = list(first)
        elif isinstance(first, str):
            try:
                parsed = json.loads(first)
            except json.JSONDecodeError as exc:
                raise MtcParseError("Registro con JSON invalido.") from exc
            if isinstance(parsed, list):
                items = parsed
    records: list[dict[str, object]] = []
    for index, item in enumerate(items):
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except json.JSONDecodeError as exc:
                raise MtcParseError("Registro con JSON invalido.") from exc
        if not isinstance(item, dict):
            raise MtcParseError("Registro con formato inesperado.")
        plate = _text(item.get("PLACA"))
        if plate is None:
            raise MtcParseError("El registro no indica la placa.")
        records.append(
            {
                "posicion": index + 1,
                "etiqueta": LABELS[index] if index < len(LABELS) else f"REGISTRO_{index + 1}",
                "empresa": _text(item.get("SRAZONSOCENTCER")),
                "direccion": _text(item.get("DIRECCION")),
                "placa": normalize_plate(plate),
                "numero_certificado": _text(item.get("NRO_CERTI")),
                "tipo_documento": _text(item.get("TIPODOCUMENTO")),
                "vigencia_desde": _date(item.get("REVISIONVIGENCIAINICIO")),
                "vigencia_hasta": _date(item.get("REVISIONVIGENCIAFINAL")),
                "resultado": _text(item.get("RESULTADO")),
                "estado": _text(item.get("ESTADO")),
                "ambito": _text(item.get("TIPO_AMBITO")),
                "tipo_servicio": _text(item.get("TIPO_SERVICIO")),
                "observaciones": _text(item.get("OBSERVACION")),
            }
        )
    return records


def parse_mtc(payload: object, plate: str) -> dict[str, object]:
    plate = normalize_plate(plate)
    if not isinstance(payload, dict) or payload.get("orStatus") is not True:
        raise MtcParseError("La respuesta no es una consulta exitosa.")
    records = _records(payload.get("orResult"))
    for record in records:
        if record["placa"] != plate:
            raise MtcParseError("La respuesta corresponde a otra placa.")
    current = next((item for item in records if item["estado"] == "VIGENTE"), None)
    return {
        "encontrado": True,
        "vigente": current,
        "registros": records,
    }


def result_from_dom_capture(capture: object, plate: str) -> QueryResult:
    """Respaldo cuando la respuesta JSON no se pudo observar en el navegador."""
    from urllib.parse import urlparse

    try:
        plate = normalize_plate(plate)
        if not isinstance(capture, dict) or capture.get("format") != "mtc-dom-v1":
            raise MtcParseError("Formato de captura no reconocido.")
        url = urlparse(str(capture.get("source_url", "")))
        if url.scheme != "https" or url.hostname not in {
            "rec.mtc.gob.pe", "portal.mtc.gob.pe"
        }:
            raise MtcParseError("La captura no indica el portal MTC esperado.")
        records = capture.get("records")
        if not isinstance(records, list):
            raise MtcParseError("El resultado visible no contiene registros.")
        payload = {
            "orStatus": True,
            "orResult": [json.dumps(item, ensure_ascii=False) for item in records],
        }
        result = result_from_response(plate, 200, payload)
        if result.status == QueryStatus.SUCCESS:
            result.data.setdefault("capture", {"method": "browser_dom"})
        return result
    except (MtcParseError, TypeError) as exc:
        return mtc_result(plate, QueryStatus.PARSE_ERROR, str(exc))


def mtc_result(
    plate: str, status: QueryStatus, message: str, data: dict | None = None
) -> QueryResult:
    return QueryResult(Source.MTC, plate, status, MTC_INFO.url, message, data or {})


def result_from_response(plate: str, status: int, payload: object) -> QueryResult:
    if status in {401, 403}:
        return mtc_result(plate, QueryStatus.REQUIRES_INTERACTION, "El portal requiere completar el captcha en el navegador.")
    if status == 429 or status >= 500:
        return mtc_result(plate, QueryStatus.UNAVAILABLE, "El portal esta ocupado o no esta disponible.")
    if status != 200:
        return mtc_result(plate, QueryStatus.UNAVAILABLE, f"La consulta devolvio HTTP {status}.")
    if not isinstance(payload, dict):
        return mtc_result(plate, QueryStatus.PARSE_ERROR, "La fuente devolvio una respuesta que no es JSON.")
    if payload.get("orStatus") is not True:
        if payload.get("orCodigo") == "-1":
            return mtc_result(
                plate,
                QueryStatus.REQUIRES_INTERACTION,
                "El codigo del captcha no fue aceptado. Vuelve a intentarlo en el navegador.",
            )
        return mtc_result(plate, QueryStatus.UNAVAILABLE, "El portal no pudo completar la consulta.")
    try:
        data = parse_mtc(payload, plate)
    except MtcParseError as exc:
        return mtc_result(plate, QueryStatus.PARSE_ERROR, str(exc))
    if not data["registros"]:
        return mtc_result(
            plate,
            QueryStatus.NOT_FOUND,
            "La fuente no encontro registros de revision tecnica para esta placa.",
            {"encontrado": False, "vigente": None, "registros": []},
        )
    return mtc_result(
        plate,
        QueryStatus.SUCCESS,
        "Consulta obtenida del portal MTC.",
        data,
    )


class MtcProvider:
    info = MTC_INFO

    def query(self, plate: str) -> QueryResult:
        return mtc_result(
            normalize_plate(plate),
            QueryStatus.REQUIRES_INTERACTION,
            "MTC requiere consulta desde la CLI: usa --stealth (desatendido, con OCR local) o --interactive (una persona lee el captcha en el navegador).",
        )
