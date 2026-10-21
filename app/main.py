from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.database import SessionLocal, engine
from app.demo_seed import seed_demo_candidates
from app.models import Base
from app.portal_service import ensure_portals
from app.routes import jd_match, job_postings, portal_search, public, recruit

BASE_DIR = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    Path("./data").mkdir(parents=True, exist_ok=True)
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_portals(db)
        if settings.demo_seed:
            seed_demo_candidates(db)
    finally:
        db.close()
    yield


app = FastAPI(title="India Talent Scout", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(public.router)
app.include_router(recruit.router)
app.include_router(jd_match.router)
app.include_router(portal_search.router)
app.include_router(job_postings.router)
app.include_router(job_postings.recruit_router)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.get("/health")
def health():
    return {"status": "up"}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 401 and request.url.path.startswith("/recruit"):
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(url="/recruit/login", status_code=303)
    if exc.status_code == 401:
        return JSONResponse(status_code=401, content={"detail": exc.detail})
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.port, reload=True)
