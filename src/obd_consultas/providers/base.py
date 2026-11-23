"""Interfaz que debe cumplir cada conector (modo ``basic``).

Los modos ``stealth`` y ``assisted`` no forman parte del provider: son runners
de infraestructura registrados en :mod:`obd_consultas.bootstrap`.
"""
from typing import Protocol

from obd_consultas.domain.models import QueryResult, SourceInfo


class VehicleProvider(Protocol):
    @property
    def info(self) -> SourceInfo: ...

    def query(self, plate: str) -> QueryResult:
        """Recibe una placa normalizada. No debe abrir interfaces interactivas."""
        ...
