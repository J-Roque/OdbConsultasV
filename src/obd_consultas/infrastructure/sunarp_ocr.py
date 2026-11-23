"""Lectura local de la tarjeta TIVE de SUNARP.

La respuesta oficial de SUNARP es una imagen PNG. Este modulo lee esa imagen con
 RapidOCR (modelo ONNX local) y expone los campos visibles como datos
 estructurados, conservando siempre la imagen original y la confianza de cada
 lectura. No reemplaza al certificado: es una lectura auxiliar.
"""
from __future__ import annotations

import base64
import re
from typing import Any

from obd_consultas.domain.models import QueryResult, normalize_plate

MIN_SCORE = 0.85
ROW_TOLERANCE = 8
WATERMARK_PARTS = (
    "SUNARP",
    "PUBLICIDAD",
    "ESTAINFORMACION",
    "SUPERINTENDENCIA",
    "REGISTROSPUBLICOS",
)
ALNUM_FIELDS = {
    "placa", "serie", "vin", "motor", "placa_vigente", "placa_anterior",
}

LABELS = {
    "placa": "NPLACA",
    "serie": "NSERIE",
    "vin": "NVIN",
    "motor": "NMOTOR",
    "color": "COLOR",
    "marca": "MARCA",
    "modelo": "MODELO",
    "placa_vigente": "PLACAVIGENTE",
    "placa_anterior": "PLACAANTERIOR",
    "estado": "ESTADO",
    "anotaciones": "ANOTACIONES",
    "sede": "SEDE",
    "anio_modelo": "ANODEMODELO",
    "propietarios": "PROPIETARIOS",
}

_ENGINE: Any = None


def _engine() -> Any:
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _ENGINE = RapidOCR()
    return _ENGINE


def _key(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _entries(items: list[Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        box, text, score = item[0], item[1], item[2]
        try:
            number = float(score)
        except (TypeError, ValueError):
            continue
        if number < MIN_SCORE or not isinstance(box, (list, tuple)) or not box:
            continue
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        key = _key(str(text))
        if any(part in key for part in WATERMARK_PARTS):
            continue
        entries.append(
            {
                "text": str(text).strip(),
                "key": key,
                "x": min(xs),
                "y": sum(ys) / len(ys),
                "score": number,
            }
        )
    entries.sort(key=lambda entry: (entry["y"], entry["x"]))
    return entries


def _normalize(field: str, value: str) -> str | list[str] | None:
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        return None
    if field in {"placa", "placa_vigente", "placa_anterior", "serie", "vin", "motor"}:
        value = re.sub(r"[^A-Z0-9]", "", value.upper())
    else:
        value = value.upper()
    if field == "estado" and value == "ENCIRCULACION":
        value = "EN CIRCULACION"
    if field == "propietarios":
        value = re.sub(r"\s*,\s*", ", ", value)
        return [part.strip() for part in value.split(",") if part.strip()]
    return value or None


def _candidate_ok(field: str, entry: dict[str, Any]) -> bool:
    key = entry["key"]
    if field in ALNUM_FIELDS:
        return len(key) >= 4 and any(character.isdigit() for character in key)
    return len(key) >= 2


def fields_from_items(items: list[Any]) -> dict[str, Any]:
    """Convierte los resultados de RapidOCR en campos con su confianza."""
    entries = _entries(items)
    fields: dict[str, Any] = {}
    for field, label in LABELS.items():
        found = None
        for index, entry in enumerate(entries):
            if not (entry["key"] == label or entry["key"].startswith(label)):
                continue
            rest = entry["key"][len(label):]
            if rest:
                found = (rest, entry["score"])
                break
            same_row = [
                other
                for other in entries[index + 1:]
                if abs(other["y"] - entry["y"]) <= ROW_TOLERANCE
                and other["x"] > entry["x"] + 5
                and not other["key"].startswith(label)
                and _candidate_ok(field, other)
            ]
            if same_row:
                best = min(same_row, key=lambda other: other["x"])
                found = (best["text"], min(entry["score"], best["score"]))
                break
            if field == "propietarios":
                below = [
                    other
                    for other in entries[index + 1:]
                    if other["y"] > entry["y"] + ROW_TOLERANCE
                    and abs(other["x"] - entry["x"]) < 80
                ]
                if below:
                    best = below[0]
                    found = (best["text"], min(entry["score"], best["score"]))
                break
        value = _normalize(field, found[0]) if found else None
        fields[field] = {
            "valor": value,
            "confianza": round(found[1], 2) if found else None,
        }
    fields["ocr"] = "rapidocr"
    return fields


def extract_tive_fields(image: bytes) -> dict[str, Any]:
    """Ejecuta el OCR local y devuelve los campos de la tarjeta TIVE."""
    items, _ = _engine()(image)
    return fields_from_items(list(items or []))


def attach_tive_ocr(result: QueryResult, image_base64: str) -> QueryResult:
    """Anexa los campos leidos al resultado sin alterar la imagen oficial."""
    try:
        compact = "".join(str(image_base64).split())
        image = base64.b64decode(compact, validate=True)
        fields = extract_tive_fields(image)
        expected = normalize_plate(result.plate)
        matches = []
        for key in ("placa", "placa_vigente"):
            value = (fields.get(key) or {}).get("valor")
            if value:
                matches.append(normalize_plate(value) == expected)
        fields["placa_coincide"] = all(matches) if matches else None
        result.data["vehiculo"] = fields
    except Exception as exc:
        # Un fallo del OCR no invalida la consulta: la imagen sigue disponible.
        result.data["vehiculo"] = {
            "disponible": False,
            "motivo": f"No se pudo leer la tarjeta: {type(exc).__name__}.",
        }
    return result
