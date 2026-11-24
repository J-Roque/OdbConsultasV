"""Punto de ensamblaje: conecta cada fuente con sus conectores y modos.

Agregar una fuente = un provider (parser + ``SourceInfo``) en ``providers/``,
su modulo de captura en ``infrastructure/`` y una entrada aqui. La CLI y la API
no cambian: descubren los modos con ``QueryService.modes()``.

Los runners importan su modulo al ejecutarse, no al arrancar: asi la API y la
CLI no cargan Playwright, Scrapling ni el OCR hasta que de verdad se usan.
"""
from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import Any

from obd_consultas.application.queries import QueryService, Runner, RunnerKey
from obd_consultas.domain.models import QueryMode, QueryResult, Source, SourceInfo
from obd_consultas.providers.atu import AtuProvider
from obd_consultas.providers.base import VehicleProvider
from obd_consultas.providers.catalog import SOURCES
from obd_consultas.providers.mtc import MtcProvider
from obd_consultas.providers.pending import PendingProvider
from obd_consultas.providers.sat import SatProvider
from obd_consultas.providers.soat import SoatProvider
from obd_consultas.providers.sunarp import SunarpProvider
from obd_consultas.providers.sutran import SutranProvider

PROVIDERS: dict[Source, Callable[[], VehicleProvider]] = {
    Source.SOAT: SoatProvider,
    Source.SUNARP: SunarpProvider,
    Source.MTC: MtcProvider,
    Source.SUTRAN: SutranProvider,
    Source.SAT: SatProvider,
    Source.ATU: AtuProvider,
}

_INFRA = "obd_consultas.infrastructure"


def _lazy(module: str, function: str, *, assisted: bool = False) -> Runner:
    """Runner que importa ``infrastructure.<module>.<function>`` al llamarse."""

    def run(plate: str, timeout: int, **options: Any) -> QueryResult:
        target = getattr(import_module(f"{_INFRA}.{module}"), function)
        if assisted:
            # Los conectores asistidos solo aceptan el canal del navegador.
            return target(plate, timeout, options.get("browser") or "msedge")
        return target(plate, timeout, **{k: v for k, v in options.items() if v is not None})

    run.__name__ = f"{module}.{function}"
    return run


RUNNERS: dict[RunnerKey, Runner] = {
    (Source.SOAT, QueryMode.STEALTH): _lazy("soat_stealth", "query_soat_stealth"),
    (Source.SOAT, QueryMode.ASSISTED): _lazy("soat_browser", "query_soat_interactive", assisted=True),
    (Source.SUNARP, QueryMode.STEALTH): _lazy("sunarp_stealth", "query_sunarp_stealth"),
    (Source.MTC, QueryMode.STEALTH): _lazy("mtc_stealth", "query_mtc_stealth"),
    (Source.MTC, QueryMode.ASSISTED): _lazy("mtc_browser", "query_mtc_interactive", assisted=True),
    (Source.SUTRAN, QueryMode.STEALTH): _lazy("sutran_stealth", "query_sutran_stealth"),
    (Source.SAT, QueryMode.STEALTH): _lazy("sat_stealth", "query_sat_stealth"),
    (Source.ATU, QueryMode.STEALTH): _lazy("atu_stealth", "query_atu_stealth"),
}


def _provider(info: SourceInfo) -> VehicleProvider:
    provider = PROVIDERS.get(info.source)
    return provider() if provider is not None else PendingProvider(info)


def build_service() -> QueryService:
    return QueryService((_provider(info) for info in SOURCES), RUNNERS)
