"""Contrato tipado de ``QueryResult.data`` por fuente.

Los parsers producen diccionarios; estos modelos describen exactamente su forma
para que:

- la API publique el contrato en OpenAPI (y se pueda generar el cliente de la APK);
- los tests fallen si un parser agrega, quita o cambia el tipo de un campo
  (``extra="forbid"``);
- :func:`validate_data` compruebe cualquier resultado ``success``/``not_found``.

Fechas en ISO 8601 (``AAAA-MM-DD``). Los campos ``None`` significan "la fuente no
lo informo", nunca "no aplica".
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, ValidationError

from obd_consultas.domain.models import QueryResult, QueryStatus, Source

# AAAA-MM-DD; se valida el patron sin convertir a date para no alterar el JSON.
IsoDate = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Capture(Contract):
    """Como se obtuvo el resultado. Nunca contiene cookies ni tokens."""

    method: Literal[
        "stealth_api",
        "stealth_dom",
        "stealth_ocr",
        "browser_api",
        "browser_dom",
        "imported_browser_dom",
    ]
    captured_at: str | None = None
    attempts: int | None = Field(default=None, ge=1, description="Intentos de captcha (MTC)")
    history_complete: bool | None = None


# --------------------------------------------------------------------- SOAT
class SoatCertificate(Contract):
    estado: Literal["VIGENTE", "VENCIDO", "ANULADO", "FUTURO"]
    aseguradora: str
    numero_poliza: str | None
    vigencia_desde: IsoDate
    vigencia_hasta: IsoDate
    tipo_certificado: str | None
    uso_vehiculo: str | None
    clase_vehiculo: str | None


class SoatData(Contract):
    encontrado: bool
    vigente: bool = Field(description="Hay un certificado en estado VIGENTE")
    soat_vigente: SoatCertificate | None
    certificados: list[SoatCertificate]
    capture: Capture | None = None


# ------------------------------------------------------------------- SUNARP
class SunarpSede(Contract):
    prefijo: str | None
    reg_pub_id: str | None
    ofic_reg_id: str | None
    nombre: str
    fg_baja: str | None
    placa: str
    num_partida: str


class SunarpCard(Contract):
    """Tarjeta TIVE oficial. Puede contener nombres de propietarios."""

    formato: Literal["png"]
    ancho: int = Field(gt=0)
    alto: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base64: str


class OcrField(Contract):
    valor: str | None
    confianza: float | None = Field(ge=0, le=1)


class OcrListField(Contract):
    valor: list[str] | None = Field(description="Un elemento por persona")
    confianza: float | None = Field(ge=0, le=1)


class SunarpVehicle(Contract):
    """Campos leidos con OCR local de la tarjeta; revisar ``confianza``."""

    placa: OcrField
    serie: OcrField
    vin: OcrField
    motor: OcrField
    color: OcrField
    marca: OcrField
    modelo: OcrField
    placa_vigente: OcrField
    placa_anterior: OcrField
    estado: OcrField
    anotaciones: OcrField
    sede: OcrField
    anio_modelo: OcrField
    propietarios: OcrListField
    ocr: Literal["rapidocr"]
    placa_coincide: bool | None = Field(description="La placa leida coincide con la consultada")


class OcrUnavailable(Contract):
    disponible: Literal[False]
    motivo: str


class SunarpData(Contract):
    encontrado: Literal[True]
    alerta_robo: str | None
    sedes: list[SunarpSede]
    plate_verified: bool
    tarjeta: SunarpCard
    vehiculo: SunarpVehicle | OcrUnavailable | None = None
    capture: Capture | None = None


class SunarpNotFound(Contract):
    encontrado: Literal[False]


# ---------------------------------------------------------------------- MTC
class MtcRecord(Contract):
    posicion: int = Field(ge=1)
    etiqueta: str = Field(description="ULTIMO, PENULTIMO, ANTEPENULTIMO o REGISTRO_n")
    empresa: str | None
    direccion: str | None
    placa: str
    numero_certificado: str | None
    tipo_documento: str | None
    vigencia_desde: IsoDate | None
    vigencia_hasta: IsoDate | None
    resultado: str | None
    estado: str | None
    ambito: str | None
    tipo_servicio: str | None
    observaciones: str | None


class MtcData(Contract):
    encontrado: bool
    vigente: MtcRecord | None
    registros: list[MtcRecord]
    capture: Capture | None = None


# ------------------------------------------------------------------- SUTRAN
class SutranCriteria(Contract):
    tipo: Literal["placa"]
    valor: str


class SutranSource(Contract):
    nombre: str
    ok: bool


class SutranData(Contract):
    """Experimental: la forma de ``documentos`` aun no se valido con datos reales."""

    encontrado: bool
    criterio: SutranCriteria
    fuentes: list[SutranSource]
    documentos: list[dict[str, Any]]
    capture: Capture | None = None


# ---------------------------------------------------------------------- SAT
class SatOrden(Contract):
    detalle: str = Field(description="Columnas de la fila unidas con ' · '")
    campos: dict[str, str] = Field(description="Fila tal como la muestra el portal")


class SatData(Contract):
    """Validado sin orden de captura; ``ordenes`` aun es provisional."""

    tiene_orden_captura: bool
    ordenes: list[SatOrden]
    mensaje: str | None
    actualizado_al: IsoDate | None = Field(description="Fecha del informe del SAT")
    capture: Capture | None = None


# ---------------------------------------------------------------------- ATU
class AtuData(Contract):
    """Validado sin infracciones; las columnas con infracciones aun son provisionales."""

    tiene_infracciones: bool
    infracciones: list[dict[str, str]] = Field(
        description="Filas de la tabla de la pasarela; claves en snake_case (placa, falta, total_a_pagar, estado...)"
    )
    total_registros: int = Field(description="Total que indica el contador de la tabla")
    completo: bool = Field(description="False si la tabla tenia mas paginas que no se leyeron")
    mensaje: str | None
    capture: Capture | None = None


# ------------------------------------------------------------------ registro
CONTRACTS: dict[Source, dict[QueryStatus, type[Contract] | Any]] = {
    Source.SOAT: {QueryStatus.SUCCESS: SoatData, QueryStatus.NOT_FOUND: SoatData},
    Source.SUNARP: {QueryStatus.SUCCESS: SunarpData, QueryStatus.NOT_FOUND: SunarpNotFound},
    Source.MTC: {QueryStatus.SUCCESS: MtcData, QueryStatus.NOT_FOUND: MtcData},
    Source.SUTRAN: {QueryStatus.SUCCESS: SutranData, QueryStatus.NOT_FOUND: SutranData},
    Source.SAT: {QueryStatus.SUCCESS: SatData, QueryStatus.NOT_FOUND: SatData},
    Source.ATU: {QueryStatus.SUCCESS: AtuData, QueryStatus.NOT_FOUND: AtuData},
}

ALL_MODELS: tuple[type[Contract], ...] = (
    SoatData,
    SunarpData,
    SunarpNotFound,
    MtcData,
    SutranData,
    SatData,
    AtuData,
)


class ContractError(ValueError):
    """``QueryResult.data`` no cumple el contrato de su fuente."""


def validate_data(result: QueryResult) -> Contract | None:
    """Valida ``data`` de un resultado final. Otros estados deben traer ``data`` vacio."""
    model = CONTRACTS.get(result.source, {}).get(result.status)
    if model is None:
        if result.data:
            raise ContractError(
                f"{result.source.value}/{result.status.value} no deberia traer datos: {sorted(result.data)}"
            )
        return None
    try:
        return TypeAdapter(model).validate_python(result.data)
    except ValidationError as exc:
        raise ContractError(f"{result.source.value}/{result.status.value}: {exc}") from exc
