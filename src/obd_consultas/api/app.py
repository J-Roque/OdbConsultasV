"""API local versionada. No ejecuta el inspector interactivo.

``POST /v1/queries/stealth`` es el puente para clientes como una APK: encola la
consulta real en un hilo, ejecuta el navegador sigiloso en la PC y permite
consultar el resultado por ``GET /v1/jobs/{job_id}``. Los trabajos viven solo en
memoria; reiniciar el proceso los descarta.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import os
import threading
import uuid
from typing import Any, Callable, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from obd_consultas.application.queries import QueryService
from obd_consultas.bootstrap import build_service
from obd_consultas.domain.models import (
    InvalidPlate,
    QueryResult,
    QueryStatus,
    Source,
    normalize_plate,
)

StealthRunner = Callable[[str, str, int], QueryResult]
MAX_JOBS = 100
TOKEN_HEADER = "X-OBD-Token"
TOKEN_ENV = "OBD_API_TOKEN"


class QueryRequest(BaseModel):
    source: Source
    plate: str = Field(min_length=1, max_length=32)


class QueryResponse(BaseModel):
    source: Source
    plate: str
    status: QueryStatus
    source_url: str
    message: str
    data: dict[str, Any]
    queried_at: datetime


class SourceResponse(BaseModel):
    source: Source
    name: str
    url: str
    implemented: bool


class StealthQueryRequest(BaseModel):
    source: Literal["soat", "sunarp", "mtc", "sutran"]
    plate: str = Field(min_length=1, max_length=32)
    timeout: int = Field(default=180, ge=10, le=600)


class AssistedQueryRequest(BaseModel):
    source: Literal["soat", "mtc"]
    plate: str = Field(min_length=1, max_length=32)
    timeout: int = Field(default=180, ge=10, le=600)
    browser: str = Field(default="msedge", max_length=20)


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


def _require_token(x_obd_token: str | None = Header(default=None, alias=TOKEN_HEADER)) -> None:
    expected = os.environ.get(TOKEN_ENV, "").strip()
    if expected and x_obd_token != expected:
        raise HTTPException(status_code=401, detail="Token invalido o ausente.")


def _default_runner(source: str, plate: str, timeout: int) -> QueryResult:
    """Ejecuta el conector sigiloso real en el proceso de la PC."""
    if source == "sunarp":
        from obd_consultas.infrastructure.sunarp_stealth import query_sunarp_stealth

        return query_sunarp_stealth(plate, timeout)
    if source == "mtc":
        from obd_consultas.infrastructure.mtc_stealth import query_mtc_stealth

        return query_mtc_stealth(plate, timeout)
    if source == "sutran":
        from obd_consultas.infrastructure.sutran_stealth import query_sutran_stealth

        return query_sutran_stealth(plate, timeout)
    from obd_consultas.infrastructure.soat_stealth import query_soat_stealth

    return query_soat_stealth(plate, timeout)


def _default_assisted_runner(
    source: str, plate: str, timeout: int, browser: str = "msedge"
) -> QueryResult:
    """Abre el navegador visible para que una persona resuelva el captcha."""
    if source == "mtc":
        from obd_consultas.infrastructure.mtc_browser import query_mtc_interactive

        return query_mtc_interactive(plate, timeout, browser)
    from obd_consultas.infrastructure.soat_browser import query_soat_interactive

    return query_soat_interactive(plate, timeout, browser)


def create_app(
    service: QueryService | None = None,
    *,
    stealth_runner: StealthRunner | None = None,
    assisted_runner: Callable[..., QueryResult] | None = None,
) -> FastAPI:
    queries = service if service is not None else build_service()
    runner = stealth_runner if stealth_runner is not None else _default_runner
    assisted = assisted_runner if assisted_runner is not None else _default_assisted_runner
    jobs: dict[str, _Job] = {}
    jobs_lock = threading.Lock()
    work_lock = threading.Lock()

    def _enqueue(source: str, plate: str, timeout: int, work_fn: Callable[[], QueryResult]) -> dict[str, str]:
        job = _Job(job_id=uuid.uuid4().hex)
        with jobs_lock:
            if len(jobs) >= MAX_JOBS:
                oldest = next(iter(jobs))
                jobs.pop(oldest, None)
            jobs[job.job_id] = job
        source_url = queries.source_info(Source(source)).url

        def work() -> None:
            with work_lock:
                job.state = "running"
                try:
                    job.result = work_fn()
                except Exception as exc:  # el cliente siempre recibe un QueryResult
                    job.result = QueryResult(
                        Source(source),
                        plate,
                        QueryStatus.UNAVAILABLE,
                        source_url,
                        f"No se pudo completar la consulta: {type(exc).__name__}.",
                    )
                finally:
                    job.state = "done"

        threading.Thread(target=work, daemon=True, name=f"query-{job.job_id[:8]}").start()
        return {
            "job_id": job.job_id,
            "state": job.state,
            "poll_url": f"/v1/jobs/{job.job_id}",
        }

    app = FastAPI(title="OBD Consultas", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/sources", response_model=list[SourceResponse], dependencies=[Depends(_require_token)])
    def sources():
        return [asdict(info) for info in queries.sources()]

    @app.post("/v1/queries", response_model=QueryResponse, dependencies=[Depends(_require_token)])
    def query(request: QueryRequest):
        try:
            return queries.query(request.source, request.plate).to_dict()
        except InvalidPlate as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post(
        "/v1/queries/stealth",
        response_model=JobCreatedResponse,
        status_code=202,
        dependencies=[Depends(_require_token)],
    )
    def stealth_query(request: StealthQueryRequest):
        try:
            plate = normalize_plate(request.plate)
        except InvalidPlate as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        source, timeout = request.source, request.timeout
        return _enqueue(source, plate, timeout, lambda: runner(source, plate, timeout))

    @app.post(
        "/v1/queries/assisted",
        response_model=JobCreatedResponse,
        status_code=202,
        dependencies=[Depends(_require_token)],
    )
    def assisted_query(request: AssistedQueryRequest):
        try:
            plate = normalize_plate(request.plate)
        except InvalidPlate as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        source, timeout = request.source, request.timeout
        browser = request.browser.strip() or "msedge"
        return _enqueue(
            source,
            plate,
            timeout,
            lambda: assisted(source, plate, timeout, browser),
        )

    @app.get("/v1/jobs/{job_id}", response_model=JobResponse, dependencies=[Depends(_require_token)])
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
