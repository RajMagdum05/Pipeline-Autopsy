"""Apply numbered, transactional Autopsy schema migrations."""
import re
from pathlib import Path

from sqlalchemy import inspect, text


MIGRATIONS_DIR = Path(__file__).with_name("migrations")
_MIGRATION_NAME = re.compile(r"^(\d+)_.*\.sql$")


def _widen_legacy_execution_ids(connection):
    """Widen legacy execution IDs for the 38-character ``trace:<trace-id>`` fallback."""
    if connection.dialect.name != "postgresql":
        return
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    parent_table = "autopsy_executions"
    if parent_table not in tables:
        return
    parent_id = next((column for column in inspector.get_columns(parent_table) if column["name"] == "id"), None)
    if parent_id is None or getattr(parent_id["type"], "length", None) in (None, 64):
        return

    references = []
    for table in sorted(tables - {parent_table}):
        for foreign_key in inspector.get_foreign_keys(table):
            if foreign_key.get("referred_table") == parent_table:
                references.append((table, foreign_key))

    quote = connection.dialect.identifier_preparer.quote
    for table, foreign_key in references:
        name = foreign_key.get("name")
        if name:
            connection.exec_driver_sql(f"ALTER TABLE {quote(table)} DROP CONSTRAINT {quote(name)}")

    connection.exec_driver_sql(
        f"ALTER TABLE {quote(parent_table)} ALTER COLUMN {quote('id')} TYPE VARCHAR(64)"
    )
    for table, foreign_key in references:
        for column_name in foreign_key.get("constrained_columns") or []:
            column = next((item for item in inspector.get_columns(table) if item["name"] == column_name), None)
            if column is not None and getattr(column["type"], "length", None) not in (None, 64):
                connection.exec_driver_sql(
                    f"ALTER TABLE {quote(table)} ALTER COLUMN {quote(column_name)} TYPE VARCHAR(64)"
                )

    for table, foreign_key in references:
        name = foreign_key.get("name")
        if not name:
            continue
        constrained = ", ".join(quote(column) for column in foreign_key.get("constrained_columns") or [])
        referred = ", ".join(quote(column) for column in foreign_key.get("referred_columns") or [])
        ondelete = (foreign_key.get("options") or {}).get("ondelete")
        delete_clause = f" ON DELETE {ondelete}" if ondelete else ""
        connection.exec_driver_sql(
            f"ALTER TABLE {quote(table)} ADD CONSTRAINT {quote(name)} "
            f"FOREIGN KEY ({constrained}) REFERENCES {quote(parent_table)} ({referred}){delete_clause}"
        )


def _migration_files():
    files = []
    for path in MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"):
        match = _MIGRATION_NAME.match(path.name)
        if match:
            files.append((match.group(1), path))
    return sorted(files)


def migrate(engine):
    """Apply every unapplied migration and return the versions applied this call."""
    applied_now = []
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version VARCHAR(32) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        applied = {row[0] for row in connection.execute(text("SELECT version FROM schema_migrations"))}
        for version, path in _migration_files():
            if version in applied:
                continue
            if version == "001":
                _widen_legacy_execution_ids(connection)
            sql = path.read_text(encoding="utf-8")
            json_type = "JSONB" if connection.dialect.name == "postgresql" else "JSON"
            sql = sql.replace("JSON_TYPE", json_type)
            for statement in sql.split(";"):
                statement = statement.strip()
                if statement:
                    connection.exec_driver_sql(statement)
            connection.execute(
                text(
                    "INSERT INTO schema_migrations (version, applied_at) "
                    "VALUES (:version, CURRENT_TIMESTAMP)"
                ),
                {"version": version},
            )
            applied_now.append(version)
        if inspect(connection).has_table("projects"):
            connection.exec_driver_sql(
                "INSERT INTO projects (id, name, created_at) "
                "VALUES ('default', 'Default', CURRENT_TIMESTAMP) ON CONFLICT (id) DO NOTHING"
            )
    return applied_now
