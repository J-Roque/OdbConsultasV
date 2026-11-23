"""Casos de uso compartidos por los puntos de entrada."""
from collections.abc import Iterable
from obd_consultas.domain.models import QueryResult, Source, SourceInfo, normalize_plate
from obd_consultas.providers.base import VehicleProvider


class QueryService:
    def __init__(self, providers: Iterable[VehicleProvider]):
        self._providers = {}
        for provider in providers:
            key = provider.info.source
            if key in self._providers:
                raise ValueError(f"Conector duplicado: {key.value}")
            self._providers[key] = provider

    def sources(self) -> list[SourceInfo]:
        return [provider.info for provider in self._providers.values()]

    def source_info(self, source: Source) -> SourceInfo:
        return self._providers[source].info

    def query(self, source: Source, plate: str) -> QueryResult:
        return self._providers[source].query(normalize_plate(plate))
