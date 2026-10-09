from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Optional

from pydantic import BeforeValidator
from pydantic_core import PydanticCustomError


def parse_decimal(value: object) -> Decimal | None:
    if value is None or (isinstance(value, str) and value == ""):
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise PydanticCustomError("decimal_type", "Input must be a decimal string or number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise PydanticCustomError("decimal_invalid", "Input must be a valid decimal") from exc
    if not result.is_finite():
        raise PydanticCustomError("decimal_not_finite", "Input must be a finite decimal")
    return result


DecimalInput = Annotated[Optional[Decimal], BeforeValidator(parse_decimal)]
