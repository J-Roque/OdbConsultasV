"""Casos de uso compartidos por los puntos de entrada (CLI y API).

``QueryService`` es la unica puerta para consultar una fuente, en cualquier modo:

- ``basic``: llama al ``VehicleProvider``; nunca abre navegadores.
- ``stealth`` / ``assisted``: llama al ``Runner`` registrado para esa fuente y modo.

Los runners se registran en :mod:`obd_consultas.bootstrap`. La CLI y la API no
conocen modulos de infraestructura: preguntan ``modes()`` y llaman ``run()``.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from obd_consultas.domain.models import (
    QueryMode,
    QueryResult,
    Source,
    SourceInfo,
    UnsupportedMode,
    normalize_plate,
)
from obd_consultas.providers.base import VehicleProvider

MIN_TIMEOUT = 10
MAX_TIMEOUT = 600


class Runner(Protocol):
    """Ejecuta una consulta real. Recibe la placa ya normalizada."""

    def __call__(self, plate: str, timeout: int, **options: Any) -> QueryResult: ...


RunnerKey = tuple[Source, QueryMode]


class QueryService:
    def __init__(
        self,
        providers: Iterable[VehicleProvider],
        runners: Mapping[RunnerKey, Runner] | None = None,
    ):
        self._providers: dict[Source, VehicleProvider] = {}
        for provider in providers:
            key = provider.info.source
            if key in self._providers:
                raise ValueError(f"Conector duplicado: {key.value}")
            self._providers[key] = provider
        self._runners: dict[RunnerKey, Runner] = dict(runners or {})
        for source, mode in self._runners:
            if source not in self._providers:
                raise ValueError(f"Runner sin conector: {source.value}/{mode.value}")
            if mode == QueryMode.BASIC:
                raise ValueError("El modo basic lo atiende el conector, no un runner.")

    def sources(self) -> list[SourceInfo]:
        return [provider.info for provider in self._providers.values()]

    def source_info(self, source: Source) -> SourceInfo:
        return self._providers[source].info

    def modes(self, source: Source) -> list[QueryMode]:
        extra = [mode for (src, mode) in self._runners if src == source]
        return [QueryMode.BASIC, *sorted(extra, key=list(QueryMode).index)]

    def supports(self, source: Source, mode: QueryMode) -> bool:
        return mode == QueryMode.BASIC or (source, mode) in self._runners

    def sources_for(self, mode: QueryMode) -> list[Source]:
        return [source for source in self._providers if self.supports(source, mode)]

    def query(self, source: Source, plate: str) -> QueryResult:
        return self._providers[source].query(normalize_plate(plate))

    def run(
        self,
        source: Source,
        plate: str,
        mode: QueryMode = QueryMode.BASIC,
        *,
        timeout: int = 180,
        **options: Any,
    ) -> QueryResult:
        """Normaliza y valida antes de abrir cualquier navegador.

        Lanza ``InvalidPlate``, ``UnsupportedMode`` o ``ValueError`` (timeout).
        """
        normalized = normalize_plate(plate)
        if mode == QueryMode.BASIC:
            return self._providers[source].query(normalized)
        runner = self._runners.get((source, mode))
        if runner is None:
            allowed = ", ".join(s.value for s in self.sources_for(mode)) or "ninguna"
            raise UnsupportedMode(
                f"El modo {mode.value} no esta disponible para {source.value}. Fuentes: {allowed}."
            )
        if not MIN_TIMEOUT <= timeout <= MAX_TIMEOUT:
            raise ValueError(
                f"El tiempo de espera debe estar entre {MIN_TIMEOUT} y {MAX_TIMEOUT} segundos."
            )
        return runner(normalized, timeout, **options)
