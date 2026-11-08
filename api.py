"""SQLite-backed synthetic inventory: items and idempotent reservations."""
import sqlite3
from contextlib import closing
from pathlib import Path

SCHEMA_VERSION = 1
BUSY_TIMEOUT_SECONDS = 5.0
MAX_ITEM_ID = 2**63 - 1
MAX_RESERVATION_QUANTITY = 1_000_000
MAX_KEY_LENGTH = 128
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "var" / "inventory.sqlite3"
RESERVATION_FIELDS = ("item_id", "quantity", "idempotency_key")
RESERVATION_COLUMNS = "id, item_id, quantity, idempotency_key, created_at"
CREATE_ITEMS_SQL = """CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY,
name TEXT NOT NULL UNIQUE, quantity INTEGER NOT NULL CHECK (quantity >= 0))"""
CREATE_RESERVATIONS_SQL = """CREATE TABLE IF NOT EXISTS reservations (
id INTEGER PRIMARY KEY AUTOINCREMENT, idempotency_key TEXT NOT NULL UNIQUE,
item_id INTEGER NOT NULL REFERENCES items(id), quantity INTEGER NOT NULL CHECK (quantity > 0),
created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))"""
SEED_ITEMS_SQL = "INSERT OR IGNORE INTO items (id, name, quantity) VALUES (1, 'Notebook', 3), (2, 'Pencil', 5)"
MIGRATIONS = {1: (CREATE_ITEMS_SQL, CREATE_RESERVATIONS_SQL, SEED_ITEMS_SQL)}


class ApiError(Exception):
    def __init__(self, status, code, message, headers=()):
        self.status, self.code, self.message, self.headers = status, code, message, headers
        super().__init__(message)


class SchemaVersionError(RuntimeError):
    pass


def _connect(db_path):
    kwargs = {"timeout": BUSY_TIMEOUT_SECONDS}
    if hasattr(sqlite3, "LEGACY_TRANSACTION_CONTROL"):
        kwargs["autocommit"] = True
    else:
        kwargs["isolation_level"] = None
    conn = sqlite3.connect(str(db_path), **kwargs)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = FULL")
    except BaseException:
        conn.close()
        raise
    return conn


def _is_busy(exc):
    code = getattr(exc, "sqlite_errorcode", None)
    if code is not None:
        return (code & 0xFF) in (5, 6)
    return "locked" in str(exc).lower() or "busy" in str(exc).lower()


def _rollback(conn):
    try:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
    except sqlite3.Error:
        pass


def _busy_error():
    return ApiError(503, "storage_busy", "storage is busy, retry with the same idempotency_key", (("Retry-After", "1"),))


def _user_version(conn):
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _refuse_newer(version):
    if version > SCHEMA_VERSION:
        raise SchemaVersionError(f"database schema version {version} is newer than supported {SCHEMA_VERSION}")


def init_db(db_path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect(db_path)) as conn:
        _refuse_newer(_user_version(conn))
        mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if mode != "delete":
            mode = str(conn.execute("PRAGMA journal_mode = DELETE").fetchone()[0]).lower()
            if mode != "delete":
                raise RuntimeError(f"cannot switch journal_mode to delete, got {mode}")
        try:
            conn.execute("BEGIN IMMEDIATE")
            version = _user_version(conn)
            _refuse_newer(version)
            for target in range(version + 1, SCHEMA_VERSION + 1):
                for statement in MIGRATIONS[target]:
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {int(target)}")
            conn.execute("COMMIT")
        except BaseException:
            _rollback(conn)
            raise


def validate_reservation(payload):
    def invalid(message):
        raise ApiError(400, "invalid_request", message)
    if type(payload) is not dict:
        invalid("body must be an object")
    if set(payload) != set(RESERVATION_FIELDS):
        invalid("body must contain exactly item_id, quantity, idempotency_key")
    item_id, quantity, key = (payload[k] for k in RESERVATION_FIELDS)
    if type(item_id) is not int or not 1 <= item_id <= MAX_ITEM_ID:
        invalid("item_id must be a positive integer")
    if type(quantity) is not int or not 1 <= quantity <= MAX_RESERVATION_QUANTITY:
        invalid("quantity must be an integer from 1 to 1000000")
    if type(key) is not str or not key.strip() or len(key) > MAX_KEY_LENGTH:
        invalid("idempotency_key must be nonblank text of at most 128 characters")
    try:
        key.encode("utf-8")
    except UnicodeEncodeError:
        invalid("idempotency_key must be valid Unicode text")
    return item_id, quantity, key


def _reservation(row):
    return dict(zip(("id", "item_id", "quantity", "idempotency_key", "created_at"), row))


class Inventory:
    def __init__(self, db_path=DEFAULT_DB_PATH):
        self.db_path = str(db_path)
        init_db(self.db_path)

    def list_items(self):
        try:
            with closing(_connect(self.db_path)) as conn:
                return [dict(zip(("id", "name", "quantity"), row)) for row in
                        conn.execute("SELECT id, name, quantity FROM items ORDER BY id")]
        except sqlite3.OperationalError as exc:
            if _is_busy(exc):
                raise _busy_error() from exc
            raise

    def reserve(self, payload):
        item_id, quantity, key = validate_reservation(payload)
        try:
            with closing(_connect(self.db_path)) as conn:
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    row = conn.execute(f"SELECT {RESERVATION_COLUMNS} FROM reservations WHERE idempotency_key = ?", (key,)).fetchone()
                    if row:
                        conn.execute("ROLLBACK")
                        if row[1] == item_id and row[2] == quantity:
                            return 200, _reservation(row)
                        raise ApiError(409, "idempotency_key_conflict", "key already used with different data")
                    item = conn.execute("SELECT quantity FROM items WHERE id = ?", (item_id,)).fetchone()
                    if item is None:
                        raise ApiError(404, "item_not_found", "item not found")
                    if item[0] < quantity:
                        raise ApiError(409, "insufficient_stock", "insufficient stock")
                    cur = conn.execute("UPDATE items SET quantity = quantity - ? WHERE id = ? AND quantity >= ?", (quantity, item_id, quantity))
                    if cur.rowcount != 1:
                        raise RuntimeError("stock changed inside write transaction")
                    cur = conn.execute("INSERT INTO reservations (idempotency_key, item_id, quantity) VALUES (?, ?, ?)", (key, item_id, quantity))
                    row = conn.execute(f"SELECT {RESERVATION_COLUMNS} FROM reservations WHERE id = ?", (cur.lastrowid,)).fetchone()
                    conn.execute("COMMIT")
                    return 201, _reservation(row)
                except BaseException:
                    _rollback(conn)
                    raise
        except sqlite3.OperationalError as exc:
            if _is_busy(exc):
                raise _busy_error() from exc
            raise
