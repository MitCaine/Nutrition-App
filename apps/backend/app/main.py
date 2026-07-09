from fastapi import FastAPI

from app.api.v1.routers import foods, health, logs, nutrients, usda


def create_app() -> FastAPI:
    app = FastAPI(title="Nutrition App API", version="0.1.0")
    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(nutrients.router, prefix="/api/v1/nutrients", tags=["nutrients"])
    app.include_router(foods.router, prefix="/api/v1/foods", tags=["foods"])
    app.include_router(logs.router, prefix="/api/v1/logs", tags=["logs"])
    app.include_router(usda.router, prefix="/api/v1/usda", tags=["usda"])
    return app


app = create_app()
