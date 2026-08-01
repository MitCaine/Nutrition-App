from collections.abc import Generator
import os

os.environ.setdefault("NUTRITION_DEPLOYMENT_MODE", "test")
os.environ.setdefault("NUTRITION_DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.catalog.nutrients import nutrient_seed_rows
from app.core.database import Base
from app.dependencies.database import get_db
from app.dependencies.user import TEST_USER_EMAIL, TEST_USER_ID
from app.main import app
from app.models import Nutrient  # noqa: F401
from app.models.user import User
from app import models  # noqa: F401
from tests.time_zone_test_support import establish_test_time_zone


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    with TestingSessionLocal() as session:
        session.add_all([Nutrient(**row) for row in nutrient_seed_rows()])
        session.commit()
        yield session


@pytest.fixture()
def unconfirmed_client(db_session: Session) -> Generator[TestClient, None, None]:
    """Return an API client whose owner has not established a calendar zone."""

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def client(
    db_session: Session,
    unconfirmed_client: TestClient,
) -> Generator[TestClient, None, None]:
    """Return the normal API client with the E1-01 mutation precondition met."""

    user = db_session.get(User, TEST_USER_ID)
    if user is None:
        user = User(id=TEST_USER_ID, email=TEST_USER_EMAIL, display_name="Test User")
        db_session.add(user)
    establish_test_time_zone(db_session, TEST_USER_ID)
    db_session.commit()
    yield unconfirmed_client
