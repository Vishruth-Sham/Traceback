from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config import get_settings


class Base(DeclarativeBase):
    pass


def build_engine(database_url: str | None = None):
    configured = database_url or get_settings().database_url
    return create_engine(configured, pool_pre_ping=True, connect_args={"options": "-c timezone=UTC"})


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
