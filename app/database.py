from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


DATABASE_URL = "sqlite:///./dreitrack.db"


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


def get_db(request: Request):
    db = SessionLocal()

    organization_id = getattr(
        request.state,
        "organization_id",
        None,
    )

    if organization_id is not None:
        db.info["organization_id"] = organization_id

    try:
        yield db
    finally:
        db.close()
