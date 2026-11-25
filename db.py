"""MySQL access layer. Every query in this project is plain SQL (no ORM).

Connections come from a pool. Before a connection is handed out, the current user's
name is stored in the MySQL session variable @app_user so the audit triggers can
record *who* changed a row.
"""
import contextvars
import os
from contextlib import contextmanager

import mysql.connector
from mysql.connector import pooling

import config  # noqa: F401  (loads .env)

CONFIG = dict(
    host=os.getenv("DB_HOST", "localhost"),
    port=int(os.getenv("DB_PORT", "3306")),
    user=os.getenv("DB_USER", "root"),
    password=os.getenv("DB_PASSWORD", ""),
    database=os.getenv("DB_NAME", "elearning_db"),
    charset="utf8mb4",
    connection_timeout=int(os.getenv("DB_CONNECT_TIMEOUT", "10")),
)
if os.getenv("DB_SOCKET"):
    CONFIG["unix_socket"] = os.getenv("DB_SOCKET")

_pool = None
_actor = contextvars.ContextVar("db_actor", default=None)


def set_actor(name):
    """Name recorded by audit triggers for changes made on this request."""
    _actor.set(name)


def get_pool():
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="eduhub", pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
            pool_reset_session=True, **CONFIG)
    return _pool


def get_conn():
    conn = get_pool().get_connection()
    cur = conn.cursor()
    cur.execute("SET @app_user = %s", (_actor.get(),))
    cur.close()
    return conn


def query(sql, params=(), one=False):
    """Run a SELECT. Returns a list of dicts, or a single dict/None when one=True."""
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        rows = cur.fetchall()
        if one:
            return rows[0] if rows else None
        return rows
    finally:
        conn.close()


def execute(sql, params=()):
    """Run a single INSERT/UPDATE/DELETE and commit. Returns lastrowid."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def execute_count(sql, params=()):
    """Like execute(), but returns the number of rows affected."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def call(proc, args=()):
    """Call a stored procedure. Returns its result sets (a list of row lists) and commits."""
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.callproc(proc, args)
        sets = [r.fetchall() for r in cur.stored_results()]
        conn.commit()
        return sets
    finally:
        conn.close()


def call_with_columns(proc, args=()):
    """Like call(), but each result set is {"columns": [...], "rows": [...]} (works for empty sets)."""
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.callproc(proc, args)
        sets = [{"columns": list(r.column_names), "rows": r.fetchall()} for r in cur.stored_results()]
        conn.commit()
        return sets
    finally:
        conn.close()


@contextmanager
def transaction():
    """Several statements, one COMMIT. Any error triggers ROLLBACK."""
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def log_event(action, entity, entity_id=None, detail=None, actor=None, ip=None):
    """Append to the audit trail through the only door the app has (sp_log_event)."""
    call("sp_log_event", (actor or _actor.get() or "system", action, entity,
                          None if entity_id is None else str(entity_id),
                          (detail or "")[:500] or None, ip))
