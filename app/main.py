from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import settings
from app.database import create_db_and_tables
from app.routers import auth, products, inventory, locations, admin
from app.routers import suppliers, purchase_orders, reservations, dashboard


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield


app = FastAPI(
    title="LeanStock API",
    description=(
        "Multi-tenant inventory management system with atomic transfers, "
        "dead stock decay, predictive reordering, reservations, and supplier PO workflows."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — reads allowed origins from env for production
_origins: List[str] = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth.router)
app.include_router(products.router)
app.include_router(inventory.router)
app.include_router(locations.router)
app.include_router(admin.router)
app.include_router(suppliers.router)
app.include_router(purchase_orders.router)
app.include_router(reservations.router)
app.include_router(dashboard.router)


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok", "service": "LeanStock API"}


@app.get("/ui", response_class=HTMLResponse, include_in_schema=False)
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def frontend():
    html_file = Path(__file__).parent.parent / "frontend" / "index.html"
    return HTMLResponse(content=html_file.read_text(encoding="utf-8"))


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
