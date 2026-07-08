from fastapi import FastAPI

from app.api.v1.routers import health, nutrients


def create_app() -> FastAPI:
    app = FastAPI(title="Nutrition App API", version="0.1.0")
    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(nutrients.router, prefix="/api/v1/nutrients", tags=["nutrients"])
    return app


app = create_app()
