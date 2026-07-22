import logging
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

logger = logging.getLogger(__name__)

_DEFAULT_SQLITE = "sqlite:///./data/aggregator.db"
_LEGACY_PG = "postgresql://user:password@localhost/health_agg"

DATABASE_URL = os.getenv("DATABASE_URL", _DEFAULT_SQLITE)

# Em produção, bloquear URL com credenciais placeholder
_env = os.getenv("ENVIRONMENT", os.getenv("ENV", "development")).lower()
if _env in {"production", "prod", "staging"}:
    if not os.getenv("DATABASE_URL"):
        raise RuntimeError(
            "DATABASE_URL é obrigatória em produção. "
            "Não use credenciais padrão user:password."
        )
    if "user:password" in DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL contém credenciais placeholder (user:password). "
            "Configure um usuário e senha reais."
        )

# SQLite precisa de check_same_thread=False para FastAPI
_connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False
    # Garante diretório local
    if "///./" in DATABASE_URL or DATABASE_URL.startswith("sqlite:///"):
        os.makedirs("data", exist_ok=True)

engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
