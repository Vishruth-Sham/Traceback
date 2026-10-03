from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from sqlalchemy.exc import IntegrityError, OperationalError

from backend.api import router
from backend.assets import router as asset_router
from backend.captures import router as capture_router
from backend.config import get_settings
from backend.errors import DomainError
from backend.locations import router as location_router
from backend.log import router as log_router
from backend.voice import router as voice_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Traceback Local API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Traceback-Client"],
    )

    @app.exception_handler(DomainError)
    async def domain_error(_request: Request, exc: DomainError):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "invalid_input", "message": "Request validation failed", "details": {"errors": jsonable_encoder(exc.errors())}}},
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error(_request: Request, _exc: IntegrityError):
        return JSONResponse(
            status_code=409,
            content={"error": {"code": "constraint_conflict", "message": "The request conflicts with stored data", "details": {}}},
        )

    @app.exception_handler(OperationalError)
    async def database_unavailable(_request: Request, _exc: OperationalError):
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "service_unavailable", "message": "PostgreSQL is unavailable", "details": {}}},
        )

    app.include_router(router)
    app.include_router(asset_router)
    app.include_router(capture_router)
    app.include_router(location_router)
    app.include_router(log_router)
    app.include_router(voice_router)
    return app


app = create_app()
