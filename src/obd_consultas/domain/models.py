"""Contrato de resultados independiente de HTTP, MAUI y Playwright."""

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
import re


class Source(str, Enum):
    SOAT = "soat"
    SUNARP = "sunarp"
    MTC = "mtc"
    SUTRAN = "sutran"
    SAT = "sat"
    ATU = "atu"
    CALLAO = "callao"


class QueryStatus(str, Enum):
    SUCCESS = "success"
    NOT_FOUND = "not_found"
    REQUIRES_INTERACTION = "requires_interaction"
    UNAVAILABLE = "unavailable"
    PARSE_ERROR = "parse_error"
    NOT_IMPLEMENTED = "not_implemented"


class QueryMode(str, Enum):
    """Como se ejecuta una consulta."""

    BASIC = "basic"        # sin navegador: valida y responde el estado del conector
    STEALTH = "stealth"    # desatendida: navegador sigiloso o HTTP + OCR
    ASSISTED = "assisted"  # navegador visible: una persona resuelve la verificacion


class UnsupportedMode(ValueError):
    """La fuente no ofrece el modo de consulta pedido."""


class InvalidPlate(ValueError):
    """La entrada no cumple el formato de placa admitido."""


def normalize_plate(value: str) -> str:
    plate = re.sub(r"[\s-]", "", value).upper()
    if not re.fullmatch(r"[A-Z0-9]{6,7}", plate):
        raise InvalidPlate("La placa debe contener 6 o 7 letras o numeros, sin otros caracteres.")
    return plate


@dataclass(frozen=True)
class SourceInfo:
    source: Source
    name: str
    url: str
    implemented: bool = False


@dataclass(frozen=True)
class QueryResult:
    source: Source
    plate: str
    status: QueryStatus
    source_url: str
    message: str
    data: dict[str, object] = field(default_factory=dict)
    queried_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["source"] = self.source.value
        result["status"] = self.status.value
        result["queried_at"] = self.queried_at.isoformat()
        return result
