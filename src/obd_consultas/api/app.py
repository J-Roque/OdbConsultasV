"""API local versionada. No ejecuta el inspector interactivo.

``POST /v1/queries/stealth`` es el puente para clientes como una APK: encola la
consulta real en un hilo, ejecuta el navegador sigiloso en la PC y permite
consultar el resultado por ``GET /v1/jobs/{job_id}``. Los trabajos viven solo en
memoria; reiniciar el proceso los descarta.

La API no conoce conectores: delega en ``QueryService.run()``, y las fuentes
que admite cada modo salen de ``QueryService.supports()``.

Los controles de seguridad (token obligatorio, limite de peticiones, docs y modo
asistido desactivados por defecto) viven en :mod:`obd_consultas.api.security`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import threading
from typing import Any, Literal
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, Field
from pydantic.json_schema import models_json_schema

from obd_consultas.api.security import TOKEN_HEADER, TOKEN_HINT, ApiSettings, RateLimiter
from obd_consultas.application.queries import MAX_TIMEOUT, MIN_TIMEOUT, QueryService
from obd_consultas.bootstrap import build_service
from obd_consultas.contracts import ALL_MODELS
from obd_consultas.domain.models import (
    InvalidPlate,
    QueryMode,
    QueryResult,
    QueryStatus,
    Source,
    normalize_plate,
)

MAX_JOBS = 100
Plate = Field(min_length=1, max_length=32)
Timeout = Field(default=180, ge=MIN_TIMEOUT, le=MAX_TIMEOUT)


# `data` segun la fuente; objeto vacio en estados no finales.
_DATA_SCHEMA: dict[str, Any] = {
    "anyOf": [{"$ref": f"#/components/schemas/{m.__name__}"} for m in ALL_MODELS]
    + [{"type": "object", "maxProperties": 0}],
}


class QueryRequest(BaseModel):
    source: Source
    plate: str = Plate


class QueryResponse(BaseModel):
    source: Source
    plate: str
    status: QueryStatus
    source_url: str
    message: str
    data: dict[str, Any] = Field(
        description=(
            "Depende de `source` y `status`: en `success`/`not_found` sigue el contrato "
            "de la fuente (SoatData, SunarpData, SunarpNotFound, MtcData, SutranData); "
            "en los demas estados viene vacio."
        ),
        json_schema_extra=_DATA_SCHEMA,
    )
    queried_at: datetime


class SourceResponse(BaseModel):
    source: Source
    name: str
    url: str
    implemented: bool
    modes: list[QueryMode]


class StealthQueryRequest(BaseModel):
    source: Source
    plate: str = Plate
    timeout: int = Timeout


class AssistedQueryRequest(BaseModel):
    source: Source
    plate: str = Plate
    timeout: int = Timeout
    browser: Literal["msedge", "chrome", "chromium"] = "msedge"


class JobCreatedResponse(BaseModel):
    job_id: str
    state: str
    poll_url: str


class JobResponse(BaseModel):
    job_id: str
    state: str
    result: QueryResponse | None = None


@dataclass
class _Job:
    job_id: str
    state: str = "pending"
    result: QueryResult | None = None


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


def create_app(
    service: QueryService | None = None,
    *,
    settings: ApiSettings | None = None,
) -> FastAPI:
    config = settings if settings is not None else ApiSettings.from_env()
    limiter = RateLimiter(config.rate_limit_per_minute)
    queries = service if service is not None else build_service()
    jobs: dict[str, _Job] = {}
    jobs_lock = threading.Lock()
    work_lock = threading.Lock()

    def guard(
        request: Request,
        x_obd_token: str | None = Header(default=None, alias=TOKEN_HEADER),
    ) -> None:
        # Primero el limite (frena fuerza bruta), luego el token (fail-closed).
        client = request.client.host if request.client else "desconocido"
        wait = limiter.retry_after(client)
        if wait:
            raise HTTPException(
                status_code=429,
                detail="Demasiadas peticiones. Intenta mas tarde.",
                headers={"Retry-After": str(wait)},
            )
        if config.token_problem is not None:
            raise HTTPException(
                status_code=503,
                detail=f"API sin autenticacion configurada. {TOKEN_HINT}",
            )
        if not config.token_matches(x_obd_token):
            raise HTTPException(status_code=401, detail="Token invalido o ausente.")

    protected = [Depends(guard)]

    def _validated(source: Source, raw_plate: str, mode: QueryMode) -> str:
        if not queries.supports(source, mode):
            allowed = ", ".join(s.value for s in queries.sources_for(mode))
            raise _unprocessable(f"El modo {mode.value} no admite {source.value}. Fuentes: {allowed}.")
        try:
            return normalize_plate(raw_plate)
        except InvalidPlate as exc:
            raise _unprocessable(str(exc)) from exc

    def _enqueue(
        source: Source, plate: str, mode: QueryMode, timeout: int, **options: Any
    ) -> dict[str, str]:
        job = _Job(job_id=uuid.uuid4().hex)
        with jobs_lock:
            active = sum(1 for j in jobs.values() if j.state != "done")
            if active >= config.max_active_jobs:
                raise HTTPException(
                    status_code=429,
                    detail="Hay demasiadas consultas en curso. Espera a que terminen.",
                    headers={"Retry-After": "30"},
                )
            while len(jobs) >= MAX_JOBS:
                done = next((k for k, j in jobs.items() if j.state == "done"), None)
                jobs.pop(done if done is not None else next(iter(jobs)), None)
            jobs[job.job_id] = job

        def work() -> None:
            with work_lock:
                job.state = "running"
                try:
                    job.result = queries.run(source, plate, mode, timeout=timeout, **options)
                except Exception as exc:  # el cliente siempre recibe un QueryResult
                    job.result = QueryResult(
                        source,
                        plate,
                        QueryStatus.UNAVAILABLE,
                        queries.source_info(source).url,
                        f"No se pudo completar la consulta: {type(exc).__name__}.",
                    )
                finally:
                    job.state = "done"

        threading.Thread(target=work, daemon=True, name=f"query-{job.job_id[:8]}").start()
        return {"job_id": job.job_id, "state": job.state, "poll_url": f"/v1/jobs/{job.job_id}"}

    docs = config.enable_docs
    app = FastAPI(
        title="OBD Consultas",
        version="0.1.0",
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )

    def openapi() -> dict[str, Any]:
        # Publica los contratos por fuente para generar el cliente de la APK.
        if app.openapi_schema is None:
            schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
            _, defs = models_json_schema(
                [(model, "serialization") for model in ALL_MODELS],
                ref_template="#/components/schemas/{model}",
            )
            schema.setdefault("components", {}).setdefault("schemas", {}).update(defs.get("$defs", {}))
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        # Las respuestas traen placas y datos personales: que no se cacheen.
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/sources", response_model=list[SourceResponse], dependencies=protected)
    def sources():
        return [
            {
                "source": info.source,
                "name": info.name,
                "url": info.url,
                "implemented": info.implemented,
                "modes": queries.modes(info.source),
            }
            for info in queries.sources()
        ]

    @app.post("/v1/queries", response_model=QueryResponse, dependencies=protected)
    def query(request: QueryRequest):
        plate = _validated(request.source, request.plate, QueryMode.BASIC)
        return queries.run(request.source, plate).to_dict()

    @app.post(
        "/v1/queries/stealth",
        response_model=JobCreatedResponse,
        status_code=202,
        dependencies=protected,
    )
    def stealth_query(request: StealthQueryRequest):
        plate = _validated(request.source, request.plate, QueryMode.STEALTH)
        return _enqueue(request.source, plate, QueryMode.STEALTH, request.timeout)

    @app.post(
        "/v1/queries/assisted",
        response_model=JobCreatedResponse,
        status_code=202,
        dependencies=protected,
    )
    def assisted_query(request: AssistedQueryRequest):
        if not config.enable_assisted:
            raise HTTPException(
                status_code=403,
                detail="Consulta asistida deshabilitada en esta API. Define OBD_API_ASSISTED=1 para habilitarla.",
            )
        plate = _validated(request.source, request.plate, QueryMode.ASSISTED)
        return _enqueue(
            request.source, plate, QueryMode.ASSISTED, request.timeout, browser=request.browser
        )

    @app.get("/v1/jobs/{job_id}", response_model=JobResponse, dependencies=protected)
    def job_status(job_id: str):
        with jobs_lock:
            job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
        payload: dict[str, Any] = {"job_id": job.job_id, "state": job.state}
        if job.result is not None:
            payload["result"] = job.result.to_dict()
        return payload

    return app
