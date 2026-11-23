"""Configuracion y controles de seguridad de la API.

Reglas:

- Autenticacion *fail-closed*: sin ``OBD_API_TOKEN`` valido las rutas ``/v1/*``
  responden 503 en lugar de quedar abiertas, sin importar como se arranque la app.
- El token se compara en tiempo constante (``hmac.compare_digest``).
- Limite de peticiones por IP con ventana deslizante, aplicado antes de validar
  el token para frenar fuerza bruta.
- ``/docs``, ``/redoc`` y ``/openapi.json`` desactivados salvo ``OBD_API_DOCS=1``.
- La consulta asistida (abre un navegador visible en la PC) desactivada salvo
  ``OBD_API_ASSISTED=1``.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hmac
import os
import threading
import time

TOKEN_HEADER = "X-OBD-Token"  # noqa: S105 - nombre de cabecera, no un secreto
TOKEN_ENV = "OBD_API_TOKEN"  # noqa: S105 - nombre de variable, no un secreto
MIN_TOKEN_LENGTH = 32
TOKEN_HINT = (
    "Genera uno con: uv run obd-consultas token  "
    f"(minimo {MIN_TOKEN_LENGTH} caracteres) y guardalo en .env como {TOKEN_ENV}."
)

_TRUE = {"1", "true", "yes", "si", "on"}


def _flag(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in _TRUE


def _int(env: Mapping[str, str], name: str, default: int, minimum: int, maximum: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} debe ser un numero entero.") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} debe estar entre {minimum} y {maximum}.")
    return value


def token_problem(token: str | None) -> str | None:
    """Describe por que el token no sirve, o ``None`` si es valido."""
    if not token:
        return f"{TOKEN_ENV} no esta definido."
    if len(token) < MIN_TOKEN_LENGTH:
        return f"{TOKEN_ENV} es demasiado corto."
    return None


@dataclass(frozen=True)
class ApiSettings:
    api_token: str | None = None
    enable_docs: bool = False
    enable_assisted: bool = False
    rate_limit_per_minute: int = 30
    max_active_jobs: int = 5

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ApiSettings:
        env = os.environ if env is None else env
        return cls(
            api_token=env.get(TOKEN_ENV, "").strip() or None,
            enable_docs=_flag(env, "OBD_API_DOCS"),
            enable_assisted=_flag(env, "OBD_API_ASSISTED"),
            rate_limit_per_minute=_int(env, "OBD_API_RATE_LIMIT", 30, 1, 10_000),
            max_active_jobs=_int(env, "OBD_API_MAX_ACTIVE_JOBS", 5, 1, 100),
        )

    @property
    def token_problem(self) -> str | None:
        return token_problem(self.api_token)

    def token_matches(self, candidate: str | None) -> bool:
        if self.token_problem is not None or candidate is None:
            return False
        return hmac.compare_digest(candidate.encode(), self.api_token.encode())  # type: ignore[union-attr]


class RateLimiter:
    """Ventana deslizante en memoria por clave (IP del cliente)."""

    def __init__(
        self,
        limit: int,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 10_000,
    ) -> None:
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: str) -> int:
        """Registra un intento; devuelve 0 si se permite o segundos de espera."""
        now = self._clock()
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                if len(self._hits) >= self._max_keys:
                    self._purge(now)
                hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(1, int(self.window - (now - hits[0])) + 1)
            hits.append(now)
            return 0

    def _purge(self, now: float) -> None:
        stale = [k for k, v in self._hits.items() if not v or now - v[-1] >= self.window]
        for key in stale:
            del self._hits[key]
        if len(self._hits) >= self._max_keys:
            self._hits.clear()
