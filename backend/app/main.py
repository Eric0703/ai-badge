from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1.health import router as health_router
from app.auth.router import router as auth_router
from app.sessions.router import router as sessions_router
from app.artifacts.router import router as artifacts_router
from app.audit.router import router as audit_router
from app.trust.policy_engine import PolicyViolation

app = FastAPI(
    title="AI Badge API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.exception_handler(PolicyViolation)
async def policy_violation_handler(request: Request, exc: PolicyViolation):
    """Map trust-policy L1 hard-constraint violations to HTTP 403 Forbidden."""
    return JSONResponse(status_code=403, content={"detail": exc.reason})

# Mount API v1 routers
app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(sessions_router, prefix="/api/v1")
app.include_router(artifacts_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
