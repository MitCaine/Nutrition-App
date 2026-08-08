from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier, Lock

import pytest
from sqlalchemy import event, func, select

from app.dependencies.user import TEST_USER_EMAIL, TEST_USER_ID, _configured_user
from app.models.user import User
from tests.postgres_test_support import isolated_postgres_session_factory


pytestmark = pytest.mark.postgres_concurrency

POSTGRES_URL = os.getenv(
    "NUTRITION_TEST_POSTGRES_URL",
    "postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app",
)


def test_concurrent_configured_user_first_use_converges() -> None:
    with isolated_postgres_session_factory(
        database_url=POSTGRES_URL,
        schema_prefix="test_configured_user_bootstrap",
    ) as factory:
        engine = factory.kw["bind"]
        first_lookups = Barrier(2)
        lookup_lock = Lock()
        lookup_count = 0

        def synchronize_initial_lookup(
            _connection,
            _cursor,
            statement: str,
            _parameters,
            _context,
            _executemany: bool,
        ) -> None:
            nonlocal lookup_count
            if not statement.lstrip().startswith("SELECT") or "FROM users" not in statement:
                return
            with lookup_lock:
                if lookup_count >= 2:
                    return
                lookup_count += 1
            first_lookups.wait(timeout=5)

        event.listen(engine, "after_cursor_execute", synchronize_initial_lookup)

        def resolve_user() -> object:
            with factory() as db:
                return _configured_user(
                    db,
                    user_id=TEST_USER_ID,
                    email=TEST_USER_EMAIL,
                    display_name="Test User",
                    create_if_missing=True,
                ).id

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                resolved = list(executor.map(lambda _index: resolve_user(), range(2)))
        finally:
            event.remove(engine, "after_cursor_execute", synchronize_initial_lookup)

        assert resolved == [TEST_USER_ID, TEST_USER_ID]
        with factory() as db:
            assert db.scalar(
                select(func.count()).select_from(User).where(User.id == TEST_USER_ID)
            ) == 1
