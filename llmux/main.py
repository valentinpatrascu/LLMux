import logging
import time
from uuid import uuid7
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.requests import Request

from core.config import get_config_provider
from core.logging import setup_logging
from persistence.database import engine, AsyncSessionLocal
from persistence.models import IngressLog
from persistence.repositories import get_job_repository
from gateway.api.v1 import jobs
from common.concurrency import BoundedSemaphore

setup_logging()
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_app: FastAPI):

    config = get_config_provider().get_config()

    _app.state.semaphore = BoundedSemaphore(
        max_concurrent=config.max_concurrent_jobs, 
        max_waiting=config.max_queued_jobs
    )

    job_repository = get_job_repository()

    _ = await job_repository.fail_unfinished_jobs()

    yield

    # Shutdown
    await engine.dispose()

app = FastAPI(lifespan=lifespan)

app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["jobs"])

@app.middleware("http")
async def middleware(request: Request, call_next):

    start = time.perf_counter()
    request_id = uuid7()
    request.state.request_id = request_id

    status_code = 500

    try:
        response = await call_next(request)
        status_code = response.status_code
        return response 
    except Exception:
        logging.exception("Unhandled API exception")
        raise
    finally:
        try:
            async with AsyncSessionLocal() as db:
                db.add(IngressLog(
                    request_id=request.state.request_id,
                    method=request.method,
                    route=request.url.path,
                    response_status=status_code,
                    request_body_bytes=int(request.headers.get("content-length", 0)),
                    duration_ms=(time.perf_counter()-start) * 1e3
                ))
                await db.commit()
        except Exception:
            logging.exception("Could not write ingress log")