"""Interfaz que debe cumplir cada futuro conector."""
from typing import Protocol
from obd_consultas.domain.models import QueryResult, SourceInfo


class VehicleProvider(Protocol):
    info: SourceInfo

    def query(self, plate: str) -> QueryResult:
        """Recibe una placa normalizada. No debe abrir interfaces interactivas."""
        ...
