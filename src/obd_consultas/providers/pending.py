"""Conector pendiente: nunca presenta datos de ejemplo como datos consultados."""
from dataclasses import dataclass
from obd_consultas.domain.models import QueryResult, QueryStatus, SourceInfo


@dataclass(frozen=True)
class PendingProvider:
    info: SourceInfo

    def query(self, plate: str) -> QueryResult:
        return QueryResult(
            source=self.info.source,
            plate=plate,
            status=QueryStatus.NOT_IMPLEMENTED,
            source_url=self.info.url,
            message="Extraccion pendiente de implementar y validar en esta fuente.",
        )
