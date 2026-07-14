from fastapi import FastAPI

from app.api.v1.routers import foods, health, logs, nutrients, ocr, recipes, targets, usda


def create_app() -> FastAPI:
    app = FastAPI(title="Nutrition App API", version="0.1.0")
    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(nutrients.router, prefix="/api/v1/nutrients", tags=["nutrients"])
    app.include_router(foods.router, prefix="/api/v1/foods", tags=["foods"])
    app.include_router(logs.router, prefix="/api/v1/logs", tags=["logs"])
    app.include_router(targets.router, prefix="/api/v1/targets", tags=["targets"])
    app.include_router(recipes.router, prefix="/api/v1/recipes", tags=["recipes"])
    app.include_router(usda.router, prefix="/api/v1/usda", tags=["usda"])
    app.include_router(
        ocr.router,
        prefix="/api/v1/ocr/nutrition-label",
        tags=["ocr"],
    )
    return app


app = create_app()
