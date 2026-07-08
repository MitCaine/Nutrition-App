from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Optional

from pydantic import BeforeValidator


def parse_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


DecimalInput = Annotated[Optional[Decimal], BeforeValidator(parse_decimal)]
