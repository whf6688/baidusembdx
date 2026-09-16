import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import router
from .oauth import callback_router, management_router
from .config import get_settings
from .db import Base, engine, ensure_schemas
from .permission_middleware import ProjectPermissionMiddleware
from baidu_platform_core.schema import ensure_platform_schema

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.app_env == "local":
        ensure_schemas()
        ensure_platform_schema(engine)
        Base.metadata.create_all(engine)
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    settings.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="百度搜索信息流投放管理平台", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(ProjectPermissionMiddleware)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    response = await call_next(request)
    response.headers["x-request-id"] = request.state.request_id
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["x-frame-options"] = "DENY"
    response.headers["referrer-policy"] = "same-origin"
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"request_id": request.state.request_id, "status": "error", "data": None, "error": {"code": "INTERNAL_ERROR", "message": "服务暂时不可用"}})


@app.exception_handler(HTTPException)
async def handled_http_error(request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict) and exc.detail.get("code"):
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content={
                "request_id": getattr(request.state, "request_id", None),
                "status": "error",
                "data": None,
                "error": {
                    "code": str(exc.detail["code"]),
                    "message": str(exc.detail.get("message") or "请求被拒绝"),
                },
            },
        )
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={"detail": exc.detail},
    )


app.include_router(router)
app.include_router(management_router)
app.include_router(callback_router)
