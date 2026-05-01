"""Shared pytest fixtures. In-memory SQLite per test for isolation."""
import pytest

from f5e import db as f5e_db


@pytest.fixture
def con():
    """Fresh in-memory SQLite with schema applied."""
    c = f5e_db.connect(":memory:")
    f5e_db.apply_schema(c)
    yield c
    c.close()
