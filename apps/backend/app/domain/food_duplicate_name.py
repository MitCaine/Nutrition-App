from __future__ import annotations

import re
from collections.abc import Iterable

_GENERATED_COPY_SUFFIX = re.compile(r"^(?P<base>.+) Copy(?: (?P<ordinal>[1-9][0-9]*))?$")
_MAX_GENERATED_ORDINAL = 9_007_199_254_740_990


def allocate_duplicate_food_name(
    source_name: str,
    active_names: Iterable[str],
    *,
    source_is_duplicate: bool,
) -> str:
    base_name = source_name
    starting_ordinal = 1

    if source_is_duplicate:
        match = _GENERATED_COPY_SUFFIX.fullmatch(source_name)
        if match is not None:
            parsed_ordinal = int(match.group("ordinal") or "1")
            if parsed_ordinal <= _MAX_GENERATED_ORDINAL:
                base_name = match.group("base")
                starting_ordinal = parsed_ordinal + 1

    used_names = set(active_names)
    ordinal = starting_ordinal
    while ordinal <= _MAX_GENERATED_ORDINAL + 1:
        candidate = f"{base_name} Copy" if ordinal == 1 else f"{base_name} Copy {ordinal}"
        if candidate not in used_names:
            return candidate
        ordinal += 1
    raise ValueError("Duplicate Food name suffix exhausted the supported range.")
