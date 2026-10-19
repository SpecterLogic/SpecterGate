from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

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
)
from app.seed import seed_database
from app.services import maintenance, xray as xray_service
from app.services.tunnel_gateway import TunnelGateway


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_database(db)
    stop = asyncio.Event()
    worker = asyncio.create_task(maintenance.run(stop))
    app.state.tunnel_gateway = TunnelGateway()
    gateway_worker = asyncio.create_task(app.state.tunnel_gateway.run(stop))
    try:
        yield
    finally:
        stop.set()
        await worker
        await gateway_worker
        await asyncio.to_thread(xray_service.stop_process)


def create_app() -> FastAPI:
    app = FastAPI(
        title="SpecterGate Panel API",
        description="پنل یکپارچه مدیریت کاربران، نودها و اینباندهای Xray",
        version=settings.version,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["subscription-userinfo", "profile-update-interval", "profile-title"],
    )

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
            target = (dist / full_path).resolve()
            if full_path and target.is_relative_to(dist.resolve()) and target.is_file():
                return FileResponse(target)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
