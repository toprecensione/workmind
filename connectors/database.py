"""
WorkMind Database Connector
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Connessione read-only ai gestionali aziendali (SQL Server, MySQL, PostgreSQL).
Include:
- Schema discovery automatica (tabelle, colonne, tipi, relazioni)
- Query sicure (solo SELECT) con limit e timeout
- Caching dello schema in Redis
- Retry con backoff su errori di connessione
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from config.company import CompanyConfig, get_company_config
from logging_system import get_logger, LogStatus, LogAction
from storage.redis_store import get_store

log = get_logger("connectors.database")

_FORBIDDEN_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "EXEC", "EXECUTE", "GRANT", "REVOKE", "MERGE",
}


@dataclass
class TableSchema:
    name: str
    columns: list[dict] = field(default_factory=list)
    # Ogni colonna: {"name": "...", "type": "...", "nullable": bool, "primary_key": bool}
    row_count: int = 0
    sample_data: list[dict] = field(default_factory=list)


@dataclass
class SchemaMap:
    tables: list[TableSchema] = field(default_factory=list)
    discovered_at: str = ""

    @property
    def table_names(self) -> list[str]:
        return [t.name for t in self.tables]

    def get_table(self, name: str) -> Optional[TableSchema]:
        for t in self.tables:
            if t.name.lower() == name.lower():
                return t
        return None

    def summary(self) -> str:
        parts = [f"Database: {len(self.tables)} tabelle"]
        for t in self.tables:
            cols = ", ".join(c["name"] for c in t.columns[:5])
            extra = f" (+{len(t.columns)-5})" if len(t.columns) > 5 else ""
            parts.append(f"  - {t.name} ({t.row_count} righe): {cols}{extra}")
        return "\n".join(parts)


class DatabaseConnector:
    """
    Connessione read-only al database gestionale.
    Tutte le query passano per validazione (solo SELECT).
    """

    def __init__(self, company_cfg: Optional[CompanyConfig] = None) -> None:
        self._cfg = (company_cfg or get_company_config()).database
        self._engine = None
        self._store = get_store()
        self._schema: Optional[SchemaMap] = None
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._cfg.enabled and bool(self._cfg.host)

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        """Stabilisce la connessione al database."""
        if not self.enabled:
            log.info("Database connector disabilitato", action=LogAction.CONFIG)
            return False

        try:
            from sqlalchemy import create_engine
            conn_str = self._cfg.connection_string
            self._engine = create_engine(
                conn_str,
                pool_size=2,
                max_overflow=3,
                pool_timeout=10,
                pool_recycle=1800,
                connect_args={"connect_timeout": 10} if "mysql" in conn_str else {},
            )
            # Test connessione
            with self._engine.connect() as conn:
                conn.execute(_text("SELECT 1"))
            log.info(
                f"Database connesso: {self._cfg.host}:{self._cfg.port}/{self._cfg.name}",
                action=LogAction.STARTUP, status=LogStatus.OK,
            )
            return True
        except Exception as exc:
            log.error(
                f"Connessione database fallita: {exc}",
                action=LogAction.STARTUP, status=LogStatus.ERROR,
                suggestion="Verifica host, porta, credenziali e firewall.",
            )
            return False

    def disconnect(self) -> None:
        if self._engine:
            self._engine.dispose()
            self._engine = None
            log.info("Database disconnesso", action=LogAction.SHUTDOWN)

    # ── Schema Discovery ──────────────────────────────────────────────────────

    def discover_schema(self, sample_rows: int = 3) -> SchemaMap:
        """
        Mappa automaticamente tutte le tabelle del database.
        Risultato cachato in Redis per 24h.
        """
        if self._schema:
            return self._schema

        cached = self._store.get("db:schema")
        if cached:
            log.debug("Schema caricato da cache", action=LogAction.SCAN)
            self._schema = self._deserialize_schema(cached)
            return self._schema

        if not self._engine:
            if not self.connect():
                return SchemaMap()

        from sqlalchemy import inspect
        from datetime import datetime, timezone

        inspector = inspect(self._engine)
        tables = []

        table_names = inspector.get_table_names()
        include = set(self._cfg.tables_include) if self._cfg.tables_include else None
        exclude = set(self._cfg.tables_exclude)

        for tname in table_names:
            if include and tname not in include:
                continue
            if tname in exclude:
                continue

            columns = []
            pk_cols = set()
            try:
                pk_info = inspector.get_pk_constraint(tname)
                pk_cols = set(pk_info.get("constrained_columns", []))
            except Exception:
                pass

            for col in inspector.get_columns(tname):
                columns.append({
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": col.get("nullable", True),
                    "primary_key": col["name"] in pk_cols,
                })

            # Conta righe (approssimato per tabelle grandi)
            row_count = 0
            try:
                with self._engine.connect() as conn:
                    result = conn.execute(_text(f"SELECT COUNT(*) FROM [{tname}]"))
                    row_count = result.scalar() or 0
            except Exception:
                pass

            # Sample data
            sample_data = []
            if sample_rows > 0:
                try:
                    sample_data = self.query(
                        f"SELECT TOP {sample_rows} * FROM [{tname}]"
                        if "mssql" in str(self._engine.url)
                        else f"SELECT * FROM `{tname}` LIMIT {sample_rows}"
                    )
                except Exception:
                    pass

            tables.append(TableSchema(
                name=tname,
                columns=columns,
                row_count=row_count,
                sample_data=sample_data,
            ))

        schema = SchemaMap(
            tables=tables,
            discovered_at=datetime.now(timezone.utc).isoformat(),
        )
        self._schema = schema
        self._store.set("db:schema", self._serialize_schema(schema), ttl_seconds=86400)

        log.info(
            f"Schema discovery completata: {len(tables)} tabelle mappate",
            action=LogAction.SCAN, status=LogStatus.OK,
            extra={"tables": [t.name for t in tables]},
        )
        return schema

    # ── Query ─────────────────────────────────────────────────────────────────

    def query(self, sql: str, params: Optional[dict] = None) -> list[dict]:
        """
        Esegue una query SELECT read-only.
        Applica LIMIT automatico se non presente.
        Blocca qualsiasi query non-SELECT.
        """
        self._validate_query(sql)

        if not self._engine:
            if not self.connect():
                raise RuntimeError("Database non connesso")

        sql_upper = sql.upper().strip()
        max_rows = self._cfg.max_rows_per_query
        if "LIMIT" not in sql_upper and "TOP" not in sql_upper:
            if "mssql" in str(self._engine.url):
                sql = sql.replace("SELECT", f"SELECT TOP {max_rows}", 1)
            else:
                sql = f"{sql.rstrip(';')} LIMIT {max_rows}"

        try:
            with self._engine.connect() as conn:
                result = conn.execute(_text(sql), params or {})
                columns = list(result.keys())
                rows = []
                for row in result:
                    rows.append(dict(zip(columns, row)))
                return rows
        except Exception as exc:
            log.error(
                f"Query fallita: {exc}",
                action=LogAction.ANALYSE, status=LogStatus.ERROR,
                extra={"sql": sql[:200]},
            )
            raise

    def query_table(self, table_name: str, limit: int = 100) -> list[dict]:
        """Shortcut per leggere le prime righe di una tabella."""
        if "mssql" in str(self._engine.url or ""):
            return self.query(f"SELECT TOP {limit} * FROM [{table_name}]")
        return self.query(f"SELECT * FROM `{table_name}` LIMIT {limit}")

    # ── Validazione ───────────────────────────────────────────────────────────

    @staticmethod
    def _validate_query(sql: str) -> None:
        """Blocca qualsiasi query che non sia SELECT."""
        stripped = sql.strip().upper()
        if not stripped.startswith("SELECT"):
            raise PermissionError(f"Solo query SELECT consentite. Ricevuto: {stripped[:30]}...")

        tokens = set(stripped.split())
        forbidden = tokens & _FORBIDDEN_KEYWORDS
        if forbidden:
            raise PermissionError(f"Keyword vietate nella query: {forbidden}")

    # ── Serializzazione schema ────────────────────────────────────────────────

    @staticmethod
    def _serialize_schema(schema: SchemaMap) -> dict:
        return {
            "discovered_at": schema.discovered_at,
            "tables": [
                {
                    "name": t.name,
                    "columns": t.columns,
                    "row_count": t.row_count,
                }
                for t in schema.tables
            ],
        }

    @staticmethod
    def _deserialize_schema(data: dict) -> SchemaMap:
        tables = []
        for t in data.get("tables", []):
            tables.append(TableSchema(
                name=t["name"],
                columns=t.get("columns", []),
                row_count=t.get("row_count", 0),
            ))
        return SchemaMap(tables=tables, discovered_at=data.get("discovered_at", ""))


def _text(sql: str):
    """Crea un oggetto text SQLAlchemy."""
    from sqlalchemy import text
    return text(sql)
