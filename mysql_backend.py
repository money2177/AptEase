"""MySQL connections for the AptEase web server and one-time data import."""

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import os
import sqlite3
from contextlib import closing


ROOT = Path(__file__).resolve().parent
TABLES = (
    "units", "users", "occupancies", "resident_registrations", "bills",
    "payments", "tickets", "visits", "visit_requests", "complaints",
    "notices", "parking", "facilities", "bookings",
)


@dataclass(frozen=True)
class MySQLConfig:
    database: str

    def connect(self):
        import mysql.connector
        from mysql.connector.constants import ClientFlag

        try:
            connection = mysql.connector.connect(
                host=os.environ.get("APTEASE_MYSQL_HOST", "127.0.0.1"),
                port=int(os.environ.get("APTEASE_MYSQL_PORT", "3306")),
                user=os.environ.get("APTEASE_MYSQL_USER", "aptease"),
                password=os.environ.get("APTEASE_MYSQL_PASSWORD", ""),
                database=self.database,
                autocommit=True,
                time_zone="+00:00",
                client_flags=[ClientFlag.FOUND_ROWS],
            )
        except mysql.connector.Error as exc:
            raise sqlite3.OperationalError(exc.msg) from exc
        return MySQLConnection(connection)


class Row(tuple):
    def __new__(cls, values, columns):
        row = super().__new__(cls, (
            value.isoformat(" ") if isinstance(value, datetime)
            else value.isoformat() if isinstance(value, date)
            else value
            for value in values
        ))
        row.columns = columns
        return row

    def __getitem__(self, key):
        return super().__getitem__(self.columns.index(key) if isinstance(key, str) else key)


class Result:
    def __init__(self, cursor):
        self.lastrowid = cursor.lastrowid
        self.rowcount = cursor.rowcount
        columns = cursor.column_names
        self.rows = iter(Row(values, columns) for values in
                         (cursor.fetchall() if cursor.with_rows else ()))

    def fetchone(self):
        return next(self.rows, None)

    def fetchall(self):
        return list(self.rows)

    def __iter__(self):
        return self.rows


class MySQLConnection:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.connection.start_transaction(isolation_level="READ COMMITTED")
        return self

    def __exit__(self, error_type, error, traceback):
        if error_type is None:
            self.connection.commit()
        else:
            self.connection.rollback()

    def close(self):
        self.connection.close()

    def execute(self, sql, params=()):
        sql = sql.replace("u.block || '-' || u.number", "CONCAT(u.block, '-', u.number)")
        sql = sql.replace("p.name || ' (' || p.username || ')'", "CONCAT(p.name, ' (', p.username, ')')")
        sql = sql.replace("printf('%02d:00',b.hour)", "CONCAT(LPAD(b.hour, 2, '0'), ':00')")
        sql = sql.replace("max(start_date,?)", "GREATEST(start_date,?)")
        return self._run(sql, params)

    def executemany(self, sql, params):
        return self._run(sql, params, many=True)

    def _run(self, sql, params, many=False):
        from mysql.connector import Error

        with self.connection.cursor(buffered=True) as cursor:
            statement = sql.replace("?", "%s")
            try:
                if many:
                    cursor.executemany(statement, params)
                else:
                    cursor.execute(statement, params or None)
            except Error as exc:
                if exc.errno == 1644:
                    raise sqlite3.IntegrityError(exc.msg) from exc
                if exc.errno == 1062:
                    raise sqlite3.IntegrityError("UNIQUE " + exc.msg) from exc
                if exc.errno in (1048, 1264, 1406, 1451, 1452, 3819):
                    raise sqlite3.IntegrityError(exc.msg) from exc
                raise sqlite3.OperationalError(exc.msg) from exc
            return Result(cursor)


def prepare_schema(db):
    for statement in (ROOT / "mysql_schema.sql").read_text(encoding="utf-8").split(";"):
        if statement.strip():
            db.execute(statement)
    existing = {row[0] for row in db.execute(
        "SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE()"
    )}
    script = (ROOT / "mysql_payment_trigger.sql").read_text(encoding="utf-8")
    for statement in script.split("$$")[1:-1]:
        trigger_name = statement.split()[2]
        if trigger_name not in existing:
            db.execute(statement)


def import_sqlite(db, source):
    """Copy a consistent SQLite snapshot into an empty MySQL database."""
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as legacy:
        legacy.execute("BEGIN")
        with db:
            for table in TABLES:
                if db.execute(f"SELECT 1 FROM `{table}` LIMIT 1").fetchone():
                    raise ValueError("Import requires an empty MySQL database. Omit --import-sqlite after import.")
            existing = {row[0] for row in legacy.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"units", "users", "bills", "payments"} <= existing:
                raise ValueError("The SQLite file does not contain the AptEase tables.")
            for table in TABLES:
                if table not in existing:
                    continue
                rows = legacy.execute(f'SELECT * FROM "{table}"')
                columns = ",".join("`" + column[0].replace("`", "``") + "`" for column in rows.description)
                placeholders = ",".join("?" for _ in rows.description)
                while batch := rows.fetchmany(500):
                    db.executemany(f"INSERT INTO `{table}` ({columns}) VALUES ({placeholders})", batch)
