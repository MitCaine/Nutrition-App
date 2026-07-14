from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.dependencies.database import get_db
from app.dependencies.user import ensure_dev_user
from app.ocr.parser import parse_nutrition_label
from app.ocr.schemas import NutritionLabelParseInput, ParsedNutritionLabel


class OcrValidationRoute(APIRoute):
    """Keep this API's validation failures structured HTTP 400 responses."""

    def get_route_handler(self):
        original_route_handler = super().get_route_handler()

        async def validation_handler(request: Request) -> Response:
            try:
                return await original_route_handler(request)
            except RequestValidationError as exc:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "detail": {
                            "code": "invalid_ocr_parse_request",
                            # Deliberately omit validation input/context so raw OCR
                            # text is not reflected into error payloads or logs.
                            "errors": [
                                {
                                    "type": error["type"],
                                    "loc": list(error["loc"]),
                                    "msg": error["msg"],
                                }
                                for error in exc.errors()
                            ],
                        }
                    },
                )

        return validation_handler


router = APIRouter(route_class=OcrValidationRoute)


@router.post("/parse", response_model=ParsedNutritionLabel)
def parse_ocr_nutrition_label(
    payload: NutritionLabelParseInput,
    db: Session = Depends(get_db),
) -> ParsedNutritionLabel:
    # The endpoint is scoped through the same development user used elsewhere,
    # while the request and parse result themselves are never persisted.
    ensure_dev_user(db)
    return parse_nutrition_label(payload)
