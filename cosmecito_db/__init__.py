"""Persistencia compartida por la API, el bot y las migraciones."""

from cosmecito_db.database import Database
from cosmecito_db.models import Base

__all__ = ("Base", "Database")
