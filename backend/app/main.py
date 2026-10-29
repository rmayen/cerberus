from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.api import auth, cases, differential, emergency, jobs, samples, users
from app.config import settings

SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "content-security-policy": "default-src 'self'; base-uri 'none'; frame-ancestors 'none'",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers[key] = value
        return response


def create_app() -> FastAPI:
    app = FastAPI(
        title="Cerberus",
        description="Defensive malware analysis sandbox for authorized laboratory environments.",
        version="0.1.0",
    )
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "Cerberus", "environment": settings.environment}

    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(cases.router)
    app.include_router(samples.router)
    app.include_router(jobs.router)
    app.include_router(differential.router)
    app.include_router(emergency.router)

    return app


app = create_app()
