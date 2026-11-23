"""Normaliza la consulta vehicular de SUNARP.

SUNARP no devuelve una ficha JSON con los datos del vehiculo: entrega una
imagen PNG de la tarjeta TIVE y una lista de sedes registrales. Este conector
valida esa respuesta y la expone sin inventar campos que la fuente no publica.
"""
from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime
import hashlib
import struct
import unicodedata
from urllib.parse import urlparse

from obd_consultas.domain.models import QueryResult, QueryStatus, Source, normalize_plate
from obd_consultas.providers.catalog import SOURCES

SUNARP_INFO = next(info for info in SOURCES if info.source == Source.SUNARP)
SUNARP_FORM_URL = "https://consultavehicular.sunarp.gob.pe/consulta-vehicular/inicio"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_IMAGE_BYTES = 8_000_000
MAX_IMAGE_SIDE = 4_000


class SunarpParseError(ValueError):
    pass


def _repair_mojibake(value: str) -> str:
    """Corrige textos que el portal entrega con UTF-8 leido como cp437/cp1252."""
    if not any(marker in value for marker in ("\u251c", "\u00c3", "\u00c2")):
        return value
    for encoding in ("cp437", "latin-1"):
        try:
            fixed = value.encode(encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if fixed != value:
            return fixed
    return value


def _text(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise SunarpParseError("Campo de texto con tipo inesperado.")
    return _repair_mojibake(str(value)).strip() or None


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return decomposed.encode("ascii", "ignore").decode("ascii").lower()


def _png_info(raw: bytes) -> tuple[int, int]:
    if len(raw) > MAX_IMAGE_BYTES:
        raise SunarpParseError("La imagen de la tarjeta TIVE es demasiado grande.")
    if len(raw) < 24 or not raw.startswith(PNG_SIGNATURE) or raw[12:16] != b"IHDR":
        raise SunarpParseError("La fuente no entrego una imagen PNG valida.")
    width, height = struct.unpack(">II", raw[16:24])
    if not (0 < width <= MAX_IMAGE_SIDE and 0 < height <= MAX_IMAGE_SIDE):
        raise SunarpParseError("La imagen de la tarjeta TIVE tiene dimensiones inesperadas.")
    return width, height


def _decode_image(value: object) -> tuple[bytes, int, int]:
    if not isinstance(value, str) or not value.strip():
        raise SunarpParseError("Falta la imagen de la tarjeta TIVE.")
    compact = "".join(value.split())
    try:
        raw = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SunarpParseError("La imagen de la tarjeta TIVE no es base64 valido.") from exc
    width, height = _png_info(raw)
    return raw, width, height


def _parse_sedes(value: object, plate: str) -> list[dict[str, str | None]]:
    if not isinstance(value, list):
        raise SunarpParseError("Falta la lista de sedes registrales.")
    sedes: list[dict[str, str | None]] = []
    for item in value:
        if not isinstance(item, dict):
            raise SunarpParseError("Sede registral con formato inesperado.")
        returned = _text(item.get("placa"))
        if returned is None:
            raise SunarpParseError("La sede registral no indica la placa.")
        try:
            returned_plate = normalize_plate(returned)
        except ValueError as exc:
            raise SunarpParseError("Placa de sede registral invalida.") from exc
        if returned_plate != plate:
            raise SunarpParseError("La respuesta corresponde a otra placa.")
        name = _text(item.get("nombre"))
        partida = _text(item.get("numPartida"))
        if not name or not partida:
            raise SunarpParseError("La sede registral esta incompleta.")
        sedes.append(
            {
                "prefijo": _text(item.get("prefijo")),
                "reg_pub_id": _text(item.get("regPubId")),
                "ofic_reg_id": _text(item.get("oficRegId")),
                "nombre": name,
                "fg_baja": _text(item.get("fgBaja")),
                "placa": returned_plate,
                "num_partida": partida,
            }
        )
    return sedes


def parse_sunarp(payload: object, plate: str, *, require_sede: bool = True) -> dict[str, object]:
    """Valida una respuesta exitosa de ``getDatosVehiculo``.

    ``require_sede=False`` solo se usa con el respaldo DOM, donde la tabla de
    sedes puede no estar visible. En ese caso la placa no se puede verificar y
    el resultado lo declara explicitamente.
    """
    plate = normalize_plate(plate)
    if not isinstance(payload, dict):
        raise SunarpParseError("La respuesta no es un objeto JSON.")
    model = payload.get("model")
    if not isinstance(model, dict):
        raise SunarpParseError("La respuesta no incluye los datos del vehiculo.")
    raw, width, height = _decode_image(model.get("imagen"))
    sedes = _parse_sedes(model.get("sedes"), plate)
    if require_sede and not sedes:
        raise SunarpParseError("La respuesta no incluye la sede registral.")
    alert = _text(model.get("msgAlertaRobo"))
    return {
        "encontrado": True,
        "alerta_robo": alert,
        "sedes": sedes,
        "plate_verified": bool(sedes),
        "tarjeta": {
            "formato": "png",
            "ancho": width,
            "alto": height,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "base64": base64.b64encode(raw).decode("ascii"),
        },
    }


def _not_found(plate: str, payload: dict[str, object]) -> QueryResult:
    try:
        message = " ".join((_text(payload.get("mensaje")) or "").split())
        detail = " ".join((_text(payload.get("mensajeTxt")) or "").split())
    except SunarpParseError:
        message = detail = ""
    text = " ".join(part for part in (message, detail) if part)
    return sunarp_result(
        plate,
        QueryStatus.NOT_FOUND,
        text or "La fuente no encontro la placa consultada.",
        {"encontrado": False},
    )


def result_from_response(plate: str, status: int, payload: object) -> QueryResult:
    if status in {401, 403}:
        return sunarp_result(
            plate,
            QueryStatus.REQUIRES_INTERACTION,
            "El portal requiere completar la verificacion en el navegador.",
        )
    if status == 429 or status >= 500:
        return sunarp_result(
            plate,
            QueryStatus.UNAVAILABLE,
            "El portal esta ocupado o no esta disponible.",
        )
    if status != 200:
        return sunarp_result(plate, QueryStatus.UNAVAILABLE, f"La consulta devolvio HTTP {status}.")
    if not isinstance(payload, dict):
        return sunarp_result(
            plate,
            QueryStatus.PARSE_ERROR,
            "La fuente devolvio una respuesta que no es JSON.",
        )
    cod = payload.get("cod")
    if cod in (0, "0"):
        message = _fold(str(payload.get("mensaje") or ""))
        if "no se ha encontrado" in message or "no se encontro" in message:
            return _not_found(plate, payload)
        return sunarp_result(
            plate,
            QueryStatus.UNAVAILABLE,
            "La fuente no devolvio los datos del vehiculo.",
        )
    if cod not in (1, "1"):
        return sunarp_result(
            plate,
            QueryStatus.UNAVAILABLE,
            "La fuente devolvio una respuesta no reconocida.",
        )
    try:
        data = parse_sunarp(payload, plate)
    except SunarpParseError as exc:
        return sunarp_result(plate, QueryStatus.PARSE_ERROR, str(exc))
    message = "Consulta obtenida del portal SUNARP. La tarjeta TIVE se entrega como imagen PNG."
    if data["alerta_robo"]:
        message += " La fuente reporta una alerta: " + str(data["alerta_robo"])
    return sunarp_result(plate, QueryStatus.SUCCESS, message, data)


def result_from_dom_capture(capture: object, plate: str) -> QueryResult:
    """Respaldo cuando la respuesta JSON no se pudo observar.

    La imagen visible es la respuesta oficial del portal. Si la tabla de sedes
    no esta desplegada, la placa no se puede comprobar y se marca
    ``plate_verified=False``.
    """
    plate = normalize_plate(plate)
    try:
        if not isinstance(capture, dict) or capture.get("format") != "sunarp-dom-v1":
            raise SunarpParseError("Formato de captura no reconocido.")
        url = urlparse(str(capture.get("source_url", "")))
        if (
            url.scheme != "https"
            or url.hostname != "consultavehicular.sunarp.gob.pe"
            or not url.path.startswith("/consulta-vehicular")
        ):
            raise SunarpParseError("La captura no indica el portal SUNARP esperado.")
        image = capture.get("image")
        if not isinstance(image, str) or not image.startswith("data:image/png;base64,"):
            raise SunarpParseError("El resultado visible no contiene la imagen TIVE.")
        rows = capture.get("rows")
        if not isinstance(rows, list):
            raise SunarpParseError("El resultado visible no contiene la tabla de sedes.")
        sedes = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 4:
                raise SunarpParseError("Fila de sede registral invalida.")
            values = [str(cell).strip() for cell in row]
            sedes.append(
                {
                    "prefijo": None,
                    "reg_pub_id": None,
                    "ofic_reg_id": None,
                    "nombre": values[3],
                    "fgBaja": None,
                    "placa": values[1],
                    "numPartida": values[2],
                }
            )
        payload = {
            "cod": 1,
            "model": {
                "imagen": image.split(",", 1)[1],
                "msgAlertaRobo": capture.get("alert") or "",
                "sedes": sedes,
            },
        }
        data = parse_sunarp(payload, plate, require_sede=False)
        data["capture"] = {
            "method": "stealth_dom",
            "captured_at": datetime.now(UTC).isoformat(),
        }
        message = "Resultado visible obtenido del portal SUNARP."
        if not data["plate_verified"]:
            message += " La tabla de sedes no estaba visible: no se pudo verificar la placa en la imagen."
        return sunarp_result(plate, QueryStatus.SUCCESS, message, data)
    except SunarpParseError as exc:
        return sunarp_result(plate, QueryStatus.PARSE_ERROR, str(exc))


def sunarp_result(
    plate: str, status: QueryStatus, message: str, data: dict | None = None
) -> QueryResult:
    return QueryResult(Source.SUNARP, plate, status, SUNARP_INFO.url, message, data or {})


class SunarpProvider:
    info = SUNARP_INFO

    def query(self, plate: str) -> QueryResult:
        return sunarp_result(
            normalize_plate(plate),
            QueryStatus.REQUIRES_INTERACTION,
            "SUNARP requiere consulta desde la CLI: usa --stealth (desatendido) y completa la verificacion si el portal la pide.",
        )
