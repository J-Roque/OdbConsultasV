"""Normaliza respuestas del formulario APESEG. No reproduce tokens de Turnstile."""
from datetime import datetime
import re
from obd_consultas.domain.models import QueryResult, QueryStatus, Source, normalize_plate
from obd_consultas.providers.catalog import SOURCES

SOAT_INFO = next(info for info in SOURCES if info.source == Source.SOAT)


class SoatParseError(ValueError):
    pass


def text(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise SoatParseError("Campo de texto con tipo inesperado.")
    return str(value).strip() or None


def date(value: object) -> str | None:
    raw = text(value)
    if raw is None:
        return None
    if not re.fullmatch(r"\d{2}/\d{2}/\d{4}(?:[ T]\d{2}:\d{2}:\d{2})?", raw):
        raise SoatParseError("La fuente cambio el formato de fecha.")
    try:
        return datetime.strptime(raw[:10], "%d/%m/%Y").date().isoformat()
    except ValueError as exc:
        raise SoatParseError("Fecha invalida en la respuesta.") from exc


def parse_soat(payload: object, plate: str) -> dict[str, object]:
    plate = normalize_plate(plate)
    if not isinstance(payload, dict) or not isinstance(payload.get("placa"), str):
        raise SoatParseError("Falta la placa en la respuesta.")
    try:
        returned_plate = normalize_plate(payload["placa"])
    except ValueError as exc:
        raise SoatParseError("Placa de respuesta invalida.") from exc
    if returned_plate != plate:
        raise SoatParseError("La respuesta corresponde a otra placa.")
    certificates = payload.get("certificados")
    if not isinstance(certificates, list):
        raise SoatParseError("Falta la lista de certificados.")
    # El frontend oficial considera este literal como ausencia de certificados.
    if len(certificates) == 1 and isinstance(certificates[0], dict) and certificates[0].get("NombreCompania") == "No encontrada":
        certificates = []
    normalized = []
    for item in certificates:
        if not isinstance(item, dict):
            raise SoatParseError("Certificado con formato inesperado.")
        if item.get("Placa"):
            try:
                same_plate = normalize_plate(str(item["Placa"])) == plate
            except ValueError as exc:
                raise SoatParseError("Placa de certificado invalida.") from exc
            if not same_plate:
                raise SoatParseError("Certificado de otra placa.")
        state = (text(item.get("Estado")) or "").upper()
        company = text(item.get("NombreCompania"))
        if state not in {"VIGENTE", "VENCIDO", "ANULADO", "FUTURO"} or not company or company == "No encontrada":
            raise SoatParseError("Estado o aseguradora ausentes o desconocidos.")
        start, end = date(item.get("FechaInicio")), date(item.get("FechaFin"))
        if not start or not end or end < start:
            raise SoatParseError("Vigencia ausente o inconsistente.")
        normalized.append({
            "estado": state,
            "aseguradora": company,
            "numero_poliza": text(item.get("NumeroPoliza")),
            "vigencia_desde": start,
            "vigencia_hasta": end,
            "tipo_certificado": text(item.get("TipoCertificado")),
            "uso_vehiculo": text(item.get("NombreUsoVehiculo")),
            "clase_vehiculo": text(item.get("NombreClaseVehiculo")),
        })
    current = next((item for item in normalized if item["estado"] == "VIGENTE"), None)
    return {"encontrado": bool(normalized), "vigente": current is not None,
            "soat_vigente": current, "certificados": normalized}


def result_from_response(plate: str, status: int, payload: object) -> QueryResult:
    if status in {401, 403}:
        return soat_result(plate, QueryStatus.REQUIRES_INTERACTION,
                           "El portal requiere completar o renovar la verificacion en el navegador.")
    if status == 429 or status >= 500:
        return soat_result(plate, QueryStatus.UNAVAILABLE, "El portal esta ocupado o no esta disponible.")
    if status != 200:
        return soat_result(plate, QueryStatus.UNAVAILABLE, f"La consulta devolvio HTTP {status}.")
    try:
        data = parse_soat(payload, plate)
    except SoatParseError as exc:
        return soat_result(plate, QueryStatus.PARSE_ERROR, str(exc))
    return soat_result(plate, QueryStatus.SUCCESS if data["encontrado"] else QueryStatus.NOT_FOUND,
                       "Consulta obtenida del portal APESEG." if data["encontrado"] else "La fuente no encontro certificados para esta placa.", data)


def soat_result(plate: str, status: QueryStatus, message: str, data: dict | None = None) -> QueryResult:
    return QueryResult(Source.SOAT, plate, status, SOAT_INFO.url, message, data or {})


class SoatProvider:
    info = SOAT_INFO

    def query(self, plate: str) -> QueryResult:
        return soat_result(normalize_plate(plate), QueryStatus.REQUIRES_INTERACTION,
                           "SOAT requiere consulta desde la CLI: usa --stealth (desatendido) o --interactive (asistido) y completa la verificacion si el portal la pide.")
