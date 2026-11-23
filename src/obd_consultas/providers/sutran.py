"""Normaliza las consultas publicas de infracciones de SUTRAN."""
from __future__ import annotations

from obd_consultas.domain.models import QueryResult, QueryStatus, Source, normalize_plate
from obd_consultas.providers.catalog import SOURCES

SUTRAN_INFO = next(info for info in SOURCES if info.source == Source.SUTRAN)
SUTRAN_FORM_URL = "https://digital.sutran.gob.pe/"
SUTRAN_API_HOST = "api.dig.sutran.gob.pe"


class SutranParseError(ValueError):
    pass


def _text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, (str, int, float)):
        raise SutranParseError("Campo de documento con tipo inesperado.")
    value = str(value).strip()
    return value or None


def parse_sutran(payload: object, plate: str) -> dict[str, object]:
    plate = normalize_plate(plate)
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise SutranParseError("La fuente no devolvio una consulta exitosa.")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise SutranParseError("La respuesta no incluye el bloque de datos.")
    criterio = data.get("criterio")
    if not isinstance(criterio, dict) or criterio.get("tipo") != "placa":
        raise SutranParseError("La respuesta no corresponde a una consulta por placa.")
    returned_plate = normalize_plate(str(criterio.get("valor") or ""))
    if returned_plate != plate:
        raise SutranParseError("La respuesta corresponde a otra placa.")
    fuentes = data.get("fuentes")
    if not isinstance(fuentes, list):
        raise SutranParseError("La respuesta no incluye las fuentes consultadas.")
    fuentes_normalizadas = []
    for fuente in fuentes:
        if not isinstance(fuente, dict):
            raise SutranParseError("Fuente consultada con formato inesperado.")
        nombre = _text(fuente.get("nombre"))
        if not nombre:
            raise SutranParseError("La fuente consultada no indica su nombre.")
        fuentes_normalizadas.append({"nombre": nombre, "ok": fuente.get("ok") is True})
    documentos = data.get("documentos")
    if not isinstance(documentos, list):
        raise SutranParseError("La respuesta no incluye la lista de documentos.")
    normalized = []
    for item in documentos:
        if not isinstance(item, dict):
            raise SutranParseError("Documento con formato inesperado.")
        normalized.append({key: value for key, value in item.items() if isinstance(key, str)})
    return {
        "encontrado": bool(normalized),
        "criterio": {"tipo": "placa", "valor": returned_plate},
        "fuentes": fuentes_normalizadas,
        "documentos": normalized,
    }


def sutran_result(
    plate: str, status: QueryStatus, message: str, data: dict | None = None
) -> QueryResult:
    return QueryResult(Source.SUTRAN, plate, status, SUTRAN_INFO.url, message, data or {})


def result_from_response(plate: str, status: int, payload: object) -> QueryResult:
    plate = normalize_plate(plate)
    if status in {401, 403}:
        return sutran_result(plate, QueryStatus.REQUIRES_INTERACTION,
                              "SUTRAN requiere resolver la verificacion del portal.")
    if status == 429 or status >= 500:
        return sutran_result(plate, QueryStatus.UNAVAILABLE,
                              "SUTRAN esta ocupado o no esta disponible.")
    if status != 200:
        return sutran_result(plate, QueryStatus.UNAVAILABLE,
                              f"La consulta devolvio HTTP {status}.")
    try:
        data = parse_sutran(payload, plate)
    except (SutranParseError, ValueError) as exc:
        return sutran_result(plate, QueryStatus.PARSE_ERROR, str(exc))
    if not data["documentos"]:
        return sutran_result(
            plate,
            QueryStatus.NOT_FOUND,
            "SUTRAN no encontro documentos para esta placa.",
            data,
        )
    return sutran_result(
        plate,
        QueryStatus.SUCCESS,
        "Consulta obtenida del portal SUTRAN.",
        data,
    )


class SutranProvider:
    info = SUTRAN_INFO

    def query(self, plate: str) -> QueryResult:
        return sutran_result(
            normalize_plate(plate),
            QueryStatus.REQUIRES_INTERACTION,
            "SUTRAN permite consulta por placa, pero exige un token de Turnstile que aun no se obtiene de forma desatendida. El conector es experimental: usa --stealth para intentarlo.",
        )
