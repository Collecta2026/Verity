"""
migrate.py — bring an existing database up to date with the models.

The app gains columns as it develops (currency, FX fields, and so on). SQLAlchemy's
create_all() creates missing *tables* but never alters existing ones, so a database
created by an earlier version ends up with tables that lack the new columns — and
every page that touches them fails.

This adds any missing columns in place. It only ever ADDs: nothing is dropped,
renamed or rewritten, so existing rows and evidence are untouched.
"""
import sqlalchemy as sa


def _column_sql(col, dialect):
    """DDL type for a column, with a sensible default so existing rows stay valid."""
    try:
        type_sql = col.type.compile(dialect)
    except Exception:
        type_sql = "VARCHAR"
    sql = f"{col.name} {type_sql}"
    default = col.default.arg if (col.default is not None and
                                  not callable(getattr(col.default, "arg", None))) else None
    if default is not None and not isinstance(default, (list, dict)):
        if isinstance(default, str):
            sql += f" DEFAULT '{default}'"
        elif isinstance(default, bool):
            sql += f" DEFAULT {'TRUE' if default else 'FALSE'}"
        elif isinstance(default, (int, float)):
            sql += f" DEFAULT {default}"
    return sql


def run(db, logger=None):
    """Add any model columns that are missing from the live database.
    Returns a list of 'table.column' strings that were added."""
    engine = db.engine
    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())
    added = []

    for table in db.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue                      # create_all() handles brand-new tables
        have = {c["name"] for c in inspector.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            if col.primary_key:
                continue                  # never touch an existing primary key
            ddl = _column_sql(col, engine.dialect)
            stmt = f'ALTER TABLE "{table.name}" ADD COLUMN {ddl}'
            try:
                with engine.begin() as conn:
                    conn.execute(sa.text(stmt))
                added.append(f"{table.name}.{col.name}")
                if logger:
                    logger.info("migrate: added %s.%s", table.name, col.name)
            except Exception as ex:
                if logger:
                    logger.warning("migrate: could not add %s.%s — %s",
                                   table.name, col.name, ex)
    return added


def schema_status(db):
    """What the live database is missing, without changing anything — used by
    the health check so a mismatch is visible rather than mysterious."""
    engine = db.engine
    inspector = sa.inspect(engine)
    existing = set(inspector.get_table_names())
    missing_tables, missing_columns = [], []
    for table in db.metadata.sorted_tables:
        if table.name not in existing:
            missing_tables.append(table.name)
            continue
        have = {c["name"] for c in inspector.get_columns(table.name)}
        for col in table.columns:
            if col.name not in have:
                missing_columns.append(f"{table.name}.{col.name}")
    return {"missing_tables": missing_tables, "missing_columns": missing_columns}
