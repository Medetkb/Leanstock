"""
Test configuration.
Uses a real PostgreSQL test database so SELECT FOR UPDATE works correctly.
Make sure docker-compose is running before running tests.
"""
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, SQLModel

from app.database import get_session
from app.main import app

# Separate test database — change to your local test DB if needed
TEST_DATABASE_URL = "postgresql://postgres:postgres123@localhost:5432/leanstock_test"

test_engine = create_engine(TEST_DATABASE_URL)


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Create all tables once at the start of the test session."""
    from app.models import user, product, inventory  # noqa: F401
    SQLModel.metadata.create_all(test_engine)
    yield
    SQLModel.metadata.drop_all(test_engine)


@pytest.fixture()
def session():
    with Session(test_engine) as s:
        yield s
        s.rollback()  # roll back after each test so tests are isolated


@pytest.fixture()
def client(session):
    def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
