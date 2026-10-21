from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from urllib.parse import urlsplit

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.routers import (
    admins,
    agent,
    auth,
    dashboard,
    dns_tunnels,
    inbounds,
    nodes,
    plans,
    settings as settings_router,
    subscriptions,
    subscriptions_admin,
    users,
    xray,
    integrations,
    routing,
    wireguard,
    backups,
    security,
)
from app.seed import seed_database
from app.services import maintenance, xray as xray_service
from app.services.tunnel_gateway import TunnelGateway
from app.services import telegram_bot
from app.services.http_security import RequestBodyLimitMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_database(db)
    stop = asyncio.Event()
    worker = asyncio.create_task(maintenance.run(stop))
    app.state.tunnel_gateway = TunnelGateway()
    gateway_worker = asyncio.create_task(app.state.tunnel_gateway.run(stop))
    telegram_worker = asyncio.create_task(telegram_bot.run(stop))
    from app.services.dnstt_runtime import DnsttRuntime
    app.state.dnstt_runtime = DnsttRuntime()
    dns_worker = asyncio.create_task(app.state.dnstt_runtime.run(stop))
    try:
        yield
    finally:
        stop.set()
        await worker
        await gateway_worker
        await telegram_worker
        await dns_worker
        await asyncio.to_thread(xray_service.stop_process)


def create_app() -> FastAPI:
    app = FastAPI(
        title="SpecterGate Panel API",
        description="پنل یکپارچه مدیریت کاربران، نودها و اینباندهای Xray",
        version=settings.version,
        docs_url="/api/docs" if settings.expose_api_docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.expose_api_docs else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["subscription-userinfo", "profile-update-interval", "profile-title", "profile-web-page-url", "announce", "support-url"],
    )
    allowed_hosts = [value.strip() for value in settings.trusted_hosts.split(",") if value.strip()]
    allowed_hosts.append(settings.public_host)
    if settings.subscription_base_url:
        allowed_hosts.append(urlsplit(settings.subscription_base_url).hostname or "localhost")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(set(allowed_hosts)))
    app.add_middleware(RequestBodyLimitMiddleware)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"detail": [{"loc": error["loc"], "msg": error["msg"], "type": error["type"]} for error in exc.errors()]}, status_code=422)

    @app.middleware("http")
    async def browser_origin_guard(request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"} and (
            request.cookies.get("spectergate_session") or request.url.path == "/api/auth/session"
        ):
            origin = request.headers.get("origin")
            allowed = set(settings.cors_origin_list)
            allowed.add(str(request.base_url).rstrip("/"))
            if request.headers.get("sec-fetch-site") == "cross-site" or (origin and origin not in allowed):
                return JSONResponse({"detail": "Untrusted request origin."}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith(("/sub/", "/api/")):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'"
        if settings.expose_api_docs and request.url.path in {"/api/docs", "/docs/oauth2-redirect"}:
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' data: https://fastapi.tiangolo.com; frame-ancestors 'none'; object-src 'none'; base-uri 'none'"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    for router in (
        auth.router,
        dashboard.router,
        users.router,
        subscriptions_admin.router,
        plans.router,
        admins.router,
        nodes.router,
        inbounds.router,
        dns_tunnels.router,
        xray.router,
        settings_router.router,
        agent.router,
        integrations.router,
        routing.router,
        wireguard.router,
        backups.router,
        security.router,
    ):
        app.include_router(router, prefix=settings.api_prefix)

    # Public subscription endpoints intentionally live outside /api.
    app.include_router(subscriptions.router)

    @app.get("/api/health", tags=["system"])
    def health():
        return {"ok": True, "app": settings.app_name, "version": settings.version}

    # Optional single-origin deployment: if the frontend is built inside the
    # backend image, serve it. In the Docker topology Nginx handles this.
    dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if dist.exists():
        assets = dist / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            if full_path == 'api' or full_path.startswith(('api/', 'sub/')):
                return JSONResponse({'detail': 'Not found'}, status_code=404)
            target = (dist / full_path).resolve()
            if full_path and target.is_relative_to(dist.resolve()) and target.is_file():
                return FileResponse(target)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
