"""Punto de ensamblaje. Reemplazar un conector aqui no cambia CLI ni API."""
from obd_consultas.application.queries import QueryService
from obd_consultas.domain.models import Source, SourceInfo
from obd_consultas.providers.base import VehicleProvider
from obd_consultas.providers.catalog import SOURCES
from obd_consultas.providers.pending import PendingProvider
from obd_consultas.providers.soat import SoatProvider
from obd_consultas.providers.sunarp import SunarpProvider
from obd_consultas.providers.mtc import MtcProvider
from obd_consultas.providers.sutran import SutranProvider

PROVIDERS = {
    Source.SOAT: SoatProvider,
    Source.SUNARP: SunarpProvider,
    Source.MTC: MtcProvider,
    Source.SUTRAN: SutranProvider,
}


def _provider(info: SourceInfo) -> VehicleProvider:
    provider = PROVIDERS.get(info.source)
    return provider() if provider is not None else PendingProvider(info)


def build_service() -> QueryService:
    return QueryService(_provider(info) for info in SOURCES)
