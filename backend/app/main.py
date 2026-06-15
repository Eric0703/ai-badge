from fastapi import FastAPI
from app.api.v1.health import router as health_router
from app.auth.router import router as auth_router
from app.sessions.router import router as sessions_router
from app.artifacts.router import router as artifacts_router
from app.audit.router import router as audit_router

app = FastAPI(
    title="AI Badge API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Mount API v1 routers
app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(sessions_router, prefix="/api/v1")
app.include_router(artifacts_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
