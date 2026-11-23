"""Carga minima de archivos ``.env`` sin dependencias externas.

Formato admitido: ``CLAVE=valor`` por linea, ``#`` para comentarios, comillas
simples o dobles opcionales y prefijo ``export`` opcional. Las variables ya
definidas en el entorno tienen prioridad y nunca se sobrescriben.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import MutableMapping


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key.replace("_", "").isalnum():
            raise ValueError(f"Linea {number} invalida en .env")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


def load_env_file(path: Path, environ: MutableMapping[str, str] | None = None) -> list[str]:
    """Carga ``path`` si existe. Devuelve los nombres agregados (nunca valores)."""
    environ = os.environ if environ is None else environ
    if not path.is_file():
        return []
    added = []
    for key, value in parse_env(path.read_text(encoding="utf-8-sig")).items():
        if key not in environ:
            environ[key] = value
            added.append(key)
    return added
