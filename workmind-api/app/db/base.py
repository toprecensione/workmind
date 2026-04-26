"""
Shared SQLAlchemy Base.
Imported by both app.db.models (core) and clients.*.models (client extensions).
Keeping Base here avoids circular imports.
"""
from __future__ import annotations
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
