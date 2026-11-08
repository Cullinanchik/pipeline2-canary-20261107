# Canary 03 · План реализации резервирования синтетических товаров

task `e31339c3-5930-41a1-bfc8-e9d16810e64e` · run `0d8e4d63-a66b-496d-abbb-ee3f2763781d` · generation 5 ·
context_digest `990b7561be21a7787d77379515defa798b2fb3bd498296aca057ce9b9acc57e4`. Требования, решения и критерии — в `SPEC.md` (R1–R8, D1–D16, C1–C8, A1–A7, AC1–AC12). Машиночитаемая версия — `PLAN.json`.

Маршрут: `complex` (`ROUTE.json`). Затронуты хранилище, HTTP-слой, миграция и конкурентность. Политика проверок `.agent/project.json` **не меняется**: код остаётся в `app.py`/`api.py`, которые уже компилирует quick-проверка, а новые `tests/test_*.py` подхватывает существующий `unittest discover -s tests`. `project_policy_change` не объявляется. Генерации ассетов нет. UAT не нужен (`needs_uat: false`): UI нет, поведение API полностью проверяется автотестами, владелец в BRIEF указал «UAT не требуется».

Правила для исполнителя: выполнять шаги по порядку, буквально. Имена функций, констант, SQL, кодов ошибок и тестов — как ниже. Альтернатив нет: при расхождении с фактами исполнитель оформляет `--amendment`, а не импровизирует. Полный набор тестов не запускать (C7).

## S1. `api.py` — хранилище и правила (D1–D11, D13, D15)

Полностью заменить файл. Докстринг: `"""SQLite-backed synthetic inventory: items and idempotent reservations."""`. Импорты только `sqlite3`, `contextlib.closing`, `pathlib.Path`.

Константы:
```python
SCHEMA_VERSION = 1
BUSY_TIMEOUT_SECONDS = 5.0
MAX_ITEM_ID = 2**63 - 1
MAX_RESERVATION_QUANTITY = 1_000_000
MAX_KEY_LENGTH = 128
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "var" / "inventory.sqlite3"
RESERVATION_FIELDS = ("item_id", "quantity", "idempotency_key")
RESERVATION_COLUMNS = "id, item_id, quantity, idempotency_key, created_at"
MIGRATIONS = {1: (CREATE_ITEMS_SQL, CREATE_RESERVATIONS_SQL, SEED_ITEMS_SQL)}  # SQL — ровно SPEC §4
```

Исключения:
- `class ApiError(Exception)`: `__init__(self, status, code, message, headers=())` сохраняет `status:int`, `code:str`, `message:str`, `headers:tuple[(name, value)]`, затем вызывает `super().__init__(message)`.
- `class SchemaVersionError(RuntimeError)`.

Функции (именно эти имена; модульные константы читаются в момент вызова):
1. `_connect(db_path)`: `kwargs = {"timeout": BUSY_TIMEOUT_SECONDS}`. Если `hasattr(sqlite3, "LEGACY_TRANSACTION_CONTROL")`, то `kwargs["autocommit"] = True`, иначе `kwargs["isolation_level"] = None`. Далее `conn = sqlite3.connect(str(db_path), **kwargs)`, `PRAGMA foreign_keys = ON`, `PRAGMA synchronous = FULL`. Если PRAGMA бросила исключение — `conn.close()` и re-raise. Возвращает `conn`.
2. `_is_busy(exc)`: если есть `exc.sqlite_errorcode` (не None), вернуть `(code & 0xFF) in (5, 6)`. Иначе `"locked" in str(exc).lower() or "busy" in str(exc).lower()`.
3. `_rollback(conn)`: если `conn.in_transaction`, выполнить `ROLLBACK`; `sqlite3.Error` при этом проглатывается, потому что закрытие соединения тоже откатывает транзакцию.
4. `_busy_error()`: возвращает `ApiError(503, "storage_busy", "storage is busy, retry with the same idempotency_key", (("Retry-After", "1"),))`.
5. `init_db(db_path)`:
   - `Path(db_path).parent.mkdir(parents=True, exist_ok=True)`;
   - `with closing(_connect(db_path)) as conn:` выполнить `mode = conn.execute("PRAGMA journal_mode = DELETE").fetchone()[0]`; если `str(mode).lower() != "delete"` → `RuntimeError`;
   - `try:` `BEGIN IMMEDIATE` → `version = PRAGMA user_version`. Если `version > SCHEMA_VERSION` → `SchemaVersionError(f"database schema version {version} is newer than supported {SCHEMA_VERSION}")`. Затем `for target in range(version + 1, SCHEMA_VERSION + 1):` каждый оператор `MIGRATIONS[target]` через `conn.execute` и `conn.execute(f"PRAGMA user_version = {int(target)}")`. В конце `COMMIT`.
   - `except BaseException: _rollback(conn); raise`.
   - `executescript` и `with conn:` не использовать (D4).
6. `validate_reservation(payload)` → `(item_id, quantity, key)` или `ApiError(400, "invalid_request", <сообщение>)`. Проверки по порядку:
   - `type(payload) is dict`;
   - `set(payload) == set(RESERVATION_FIELDS)`;
   - `item_id`: `type(...) is int` и `1 <= v <= MAX_ITEM_ID`;
   - `quantity`: `type(...) is int` и `1 <= v <= MAX_RESERVATION_QUANTITY`;
   - `idempotency_key`: `type(...) is str`, `v.strip() != ""` и `len(v) <= MAX_KEY_LENGTH`.
   Ключ возвращается без изменений.
7. `_reservation(row)` → `{"id": row[0], "item_id": row[1], "quantity": row[2], "idempotency_key": row[3], "created_at": row[4]}` (порядок ключей фиксирован).
8. `class Inventory`. Хранит только `self.db_path = str(db_path)` и не держит соединений.
   - `__init__(self, db_path=DEFAULT_DB_PATH)`: `self.db_path = str(db_path)`, затем `init_db(self.db_path)`.
   - `list_items(self)`: `with closing(_connect(...))`, `SELECT id, name, quantity FROM items ORDER BY id`. Возвращает новый список новых dict `{"id", "name", "quantity"}`. `sqlite3.OperationalError`, для которой `_is_busy`, → `raise _busy_error() from exc`.
   - `reserve(self, payload)` → `(201 | 200, reservation)`:
     ```text
     item_id, quantity, key = validate_reservation(payload)        # до открытия БД
     try:
       with closing(_connect(self.db_path)) as conn:
         try:
           BEGIN IMMEDIATE
           row = SELECT RESERVATION_COLUMNS FROM reservations WHERE idempotency_key = ?
           if row: ROLLBACK; if row[1]==item_id and row[2]==quantity → return 200, _reservation(row)
                   else raise ApiError(409, "idempotency_key_conflict", ...)
           item = SELECT quantity FROM items WHERE id = ?
           if item is None: ROLLBACK; raise ApiError(404, "item_not_found", ...)
           if item[0] < quantity: ROLLBACK; raise ApiError(409, "insufficient_stock", ...)
           cur = UPDATE items SET quantity = quantity - ? WHERE id = ? AND quantity >= ?
           if cur.rowcount != 1: raise RuntimeError("stock changed inside write transaction")
           cur = INSERT INTO reservations (idempotency_key, item_id, quantity) VALUES (?, ?, ?)
           row = SELECT RESERVATION_COLUMNS FROM reservations WHERE id = ?   # cur.lastrowid
           COMMIT
           return 201, _reservation(row)
         except BaseException: _rollback(conn); raise
     except sqlite3.OperationalError as exc:
       if _is_busy(exc): raise _busy_error() from exc
       raise
     ```
     Порядок: UPDATE раньше INSERT — на этом держится тест rollback AC7. Все значения передаются параметрами `?`. `RETURNING` не использовать.

Проверка: `python3 -m py_compile api.py`.

## S2. `app.py` — HTTP-слой (D9, D10, D12, D14; SPEC §4)

Докстринг: `"""Synthetic inventory test server; no credentials or external data."""`. Импорты: `argparse, html, json, sqlite3, http.server (BaseHTTPRequestHandler, ThreadingHTTPServer), pathlib.Path, urllib.parse.urlsplit`, а также `from api import DEFAULT_DB_PATH, ApiError, Inventory, SchemaVersionError`.

1. `MAX_BODY_BYTES = 4096`.
2. `class InventoryServer(ThreadingHTTPServer)`: `daemon_threads = True`, `request_queue_size = 64`.
3. `make_server(host, port, db_path=DEFAULT_DB_PATH)`: сначала `inventory = Inventory(db_path)` (БД инициализируется до bind), затем `server = InventoryServer((host, port), Handler)`, `server.inventory = inventory`, `return server`.
4. `_reject_duplicate_keys(pairs)`: `object_pairs_hook`; повторный ключ → `ValueError`.
5. `Handler(BaseHTTPRequestHandler)`:
   - `_send_json(self, status, payload, headers=())`: `body = json.dumps(payload).encode()`, `send_response`, `Content-Type: application/json`, `Content-Length`, дополнительные заголовки, `end_headers`, `wfile.write(body)`.
   - `_send_api_error(self, err)`: `_send_json(err.status, {"error": err.code, "message": err.message}, err.headers)`.
   - `_send_internal_error(self, exc)`: `self.log_error("internal error: %r", exc)` и `_send_json(500, {"error": "internal_error", "message": "internal error"})`.
   - `do_GET`:
     - `/api/items` → `try: _send_json(200, self.server.inventory.list_items())`, `ApiError` → `_send_api_error`, `Exception` → `_send_internal_error`;
     - `/api/reservations` → `_send_api_error(ApiError(405, "method_not_allowed", "use POST", (("Allow", "POST"),)))`;
     - ветки `/health`, `/` и `send_error(404)` перенести без изменений (C2).
   - `_read_json(self)`:
     - `raw = self.headers.get("Content-Length")`; `None` → `ApiError(411, "length_required", ...)`;
     - `raw = raw.strip()`; если не `raw.isascii() and raw.isdigit()` → 400 `invalid_request`;
     - `length = int(raw)`; если `length > MAX_BODY_BYTES` → `self.close_connection = True` и `ApiError(413, "payload_too_large", ...)`, тело не читается;
     - `body = self.rfile.read(length)`; `json.loads(body.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)`; `UnicodeDecodeError`/`ValueError` → 400 `invalid_request`.
   - `do_POST`: `path = urlsplit(self.path).path`. Внутри `try`:
     - `/api/items` → `ApiError(405, "method_not_allowed", "use GET", (("Allow", "GET"),))`;
     - путь ≠ `/api/reservations` → `ApiError(404, "not_found", ...)`;
     - иначе `status, reservation = self.server.inventory.reserve(self._read_json())`.
     `except ApiError` → `_send_api_error`; `except Exception` → `_send_internal_error`; при успехе `_send_json(status, reservation)`. Ответ отправляется только после возврата `reserve`, т. е. после COMMIT.
6. `__main__`: аргументы `--host` и `--port` прежние, плюс `--db` (default `str(DEFAULT_DB_PATH)`). Вызов `server = make_server(args.host, args.port, args.db)`; `SchemaVersionError`/`sqlite3.Error` → `raise SystemExit(f"inventory database error: {exc}")`. Затем `server.serve_forever()`.

Проверка: `python3 -m py_compile app.py api.py`.

## S3. `tests/test_api.py` — сервисные тесты (AC1, AC2, AC3–AC11)

Переписать файл. Импорты: `os, re, sqlite3, subprocess, sys, tempfile, threading, unittest, ast`, `collections.Counter`, `contextlib.closing`, `pathlib.Path`, `unittest.mock`, `import api`, `from api import ApiError, Inventory, SchemaVersionError`. Константы: `ROOT = Path(__file__).resolve().parents[1]`, `INITIAL` (список SPEC §4), `SEED = {1: 3, 2: 5}`.

Базовый класс `StorageTestCase(unittest.TestCase)`:
- `setUp`: `TemporaryDirectory` + `addCleanup`, `self.db = os.path.join(tmp, "inventory.sqlite3")`, `self.inv = Inventory(self.db)`;
- хелперы `query(sql, params=())` (через `closing(api._connect(self.db))`), `stock()` → `{id: quantity}`, `reservation_count()`, `assert_invariant()` (для каждого id: `stock + COALESCE(SUM(quantity),0) == SEED[id]`), `payload(key="k-1", item_id=1, quantity=1)`.

Тесты (имена буквально):
- `InventoryStorageTests`:
  - `test_ac1_items_have_unique_ids` и `test_ac1_items_are_fresh_values` — прежние проверки на `self.inv.list_items()`;
  - `test_ac1_fresh_database_has_initial_items` (`== INITIAL`);
  - `test_ac1_reservation_reduces_listed_quantity` (qty 2 → Notebook 1);
  - `test_ac2_reserve_creates_reservation` (201, ключи, regex `created_at`, stock);
  - `test_ac2_reserve_exact_remaining_stock` (3 → 201, далее 1 → 409 `insufficient_stock`);
  - `test_ac3_invalid_payloads_rejected_without_write` — `subTest` по 22 случаям: `[]`, `"text"`, `None`, `{}`, нет `idempotency_key`, лишнее поле `note`, `item_id` = `"1"`/`True`/`0`/`2**63`/`1.0`, `quantity` = `0`/`-1`/`1.5`/`True`/`"2"`/`1_000_001`, `idempotency_key` = `""`/`"   "`/`"x"*129`/`5`/`None`. Каждый → `ApiError` со `status == 400` и `code == "invalid_request"`; после цикла `stock() == SEED` и `reservation_count() == 0`;
  - `test_ac3_unknown_item_rejected_without_write` (`item_id=999` → 404 `item_not_found`);
  - `test_ac3_insufficient_stock_rejected_without_write` (Pencil 6 → 409);
  - `test_ac4_replay_returns_original_reservation` (200, dict равен исходному, Pencil списан один раз, count 1);
  - `test_ac4_replay_after_stock_exhausted`;
  - `test_ac5_same_key_different_data_conflicts` (другой `quantity` и другой `item_id` → 409 `idempotency_key_conflict`, без изменений);
  - `test_ac5_failed_attempt_does_not_bind_key` (ключ после 409 по остатку, 404 и 400 → затем 201);
  - `test_ac7_failure_after_stock_update_rolls_back`: через отдельное соединение `CREATE TRIGGER fail_insert BEFORE INSERT ON reservations BEGIN SELECT RAISE(ABORT, 'injected failure'); END`, `assertRaises(sqlite3.IntegrityError)`, `stock() == SEED`, count 0, `assert_invariant()`. Затем `DROP TRIGGER fail_insert`, тот же ключ → 201;
  - `test_ac8_reinitialization_preserves_state` (резерв → `Inventory(self.db)` ещё дважды → stock и count прежние, повтор → 200 и тот же `id`);
  - `test_ac8_schema_version_and_journal_mode` (`user_version == 1`, `journal_mode == "delete"`);
  - `test_ac8_newer_schema_is_refused` (`PRAGMA user_version = 99` → `assertRaises(SchemaVersionError)`, после чего `user_version == 99` и `stock() == SEED`);
  - `test_ac10_connection_mode_probe` (не в транзакции → `BEGIN IMMEDIATE` → в транзакции → `ROLLBACK`; при наличии `LEGACY_TRANSACTION_CONTROL` — `conn.autocommit is True`; `sqlite3.sqlite_version_info >= (3, 7, 11)`);
  - `test_ac10_busy_database_maps_to_503`: держатель `api._connect(self.db)` + `BEGIN IMMEDIATE`, `mock.patch.object(api, "BUSY_TIMEOUT_SECONDS", 0.2)` → `ApiError` 503 `storage_busy`, `("Retry-After", "1") in err.headers`, count 0. В `finally` держатель делает `ROLLBACK`/`close`; затем тот же ключ → 201;
  - `test_ac11_only_stdlib_imports`: `ast` по `app.py` и `api.py`; корневые имена `Import`/`ImportFrom` ⊆ `{"argparse", "html", "http", "json", "pathlib", "sqlite3", "urllib", "contextlib", "api"}`.
- `ConcurrencyTests(StorageTestCase)`:
  - `test_ac6_concurrent_reservations_never_oversell`: 30 потоков, `threading.Barrier(30)`, ключи `race-{i}`, Notebook qty 1. Результаты собираются в список (`("ok", status)` / `("api", code)` / `("exc", repr)`), `join(timeout=30)` и проверка, что ни один поток не жив. Ожидание: `Counter == {("ok", 201): 3, ("api", "insufficient_stock"): 27}`, Notebook 0, count 3, `assert_invariant()`;
  - `test_ac6_concurrent_same_key_creates_one_reservation`: 10 потоков с ключом `same`, Pencil 2 → одна 201 и девять 200, множество `id` из одного элемента, Pencil 3, count 1.
- `RecoveryTests(StorageTestCase)`. Дочерний процесс: `subprocess.run([sys.executable, "-I", "-c", CODE, str(ROOT), self.db], timeout=30)`; код делает `sys.path.insert(0, sys.argv[1]); import api`.
  - `test_ac9_crash_before_commit_rolls_back`. Дочерний код: `conn = api._connect(db)`, `PRAGMA cache_size = 10`, `BEGIN IMMEDIATE`, `UPDATE items SET quantity = 0 WHERE id = 1`, `executemany` 2000 INSERT `("crash-%05d-" % i + "x" * 100, 2, 1)`, `os._exit(1)`. Родитель проверяет `returncode == 1` и `os.path.exists(self.db + "-journal")` (предусловие «горячего» журнала), затем `Inventory(self.db)`: `stock() == SEED`, count 0, `PRAGMA integrity_check == "ok"`, резерв → 201;
  - `test_ac9_committed_reservation_survives_abrupt_exit`. Дочерний код: `status, _ = api.Inventory(db).reserve({"item_id": 2, "quantity": 2, "idempotency_key": "child-commit"})`, `os._exit(0 if status == 201 else 3)`. Родитель: `returncode == 0`, Pencil 3, повтор → 200.

Проверка: `python3 -m unittest discover -s tests -p 'test_api.py' -v`.

## S4. `tests/test_reservations_http.py` — HTTP-тесты (AC1–AC8, AC10, AC11)

Новый файл. Импорты: `http.client, json, os, re, tempfile, threading, unittest`, `collections.Counter`, `contextlib.closing`, `unittest.mock`, `import api, app`.

Класс `HttpTestCase(unittest.TestCase)`:
- `setUp`: временный каталог, `mock.patch.object(app.Handler, "log_message", lambda *a, **k: None)` (start + `addCleanup(stop)`), `self.server = None`, `addCleanup(self.stop_server)`, `self.start_server()`;
- `start_server()`: `app.make_server("127.0.0.1", 0, self.db)` и поток `serve_forever(poll_interval=0.05)` с `daemon=True`;
- `stop_server()`: идемпотентно — `shutdown()`, `server_close()`, `join(10)`, `self.server = None`;
- `request(method, path, body=None, raw=None, headers=None, headers_only=False)` → `(status, {lower-header: value}, bytes)` через `http.client.HTTPConnection("127.0.0.1", port, timeout=10)`. При `headers_only=True`: `putrequest` / `putheader` / `endheaders` без тела — так шлются случаи 411 и 413, чтобы непрочитанное тело не вызвало RST;
- `post(payload)` → `(status, headers, json)`; `stock()` и `count()` — через `api._connect`.

Тесты:
- `test_ac1_get_items_initial_and_after_reservation` — 200, `application/json`, `== INITIAL`; после POST qty 2 Notebook = 1;
- `test_ac2_post_creates_reservation` — 201, набор ключей, regex `created_at`;
- `test_ac2_method_and_route_errors` — `GET /api/reservations` → 405 + `allow: POST`; `POST /api/items` → 405 + `allow: GET`; `POST /api/other` → 404 `not_found`;
- `test_ac3_invalid_requests_rejected_without_write` — raw `b"{"`, `b"\xff"`, `b"[1]"`, `b'{"item_id":1,"item_id":2,"quantity":1,"idempotency_key":"k"}'`, без ключа, `quantity: true`, `Content-Length: abc` (headers_only) → 400 `invalid_request`; без `Content-Length` (headers_only) → 411; `Content-Length: 5000` (headers_only) → 413; `item_id` 999 → 404; Pencil 6 → 409 `insufficient_stock`. В конце stock == SEED, count 0;
- `test_ac4_replay_returns_identical_body` — второй ответ 200, `body2 == body1` (bytes), Pencil списан один раз;
- `test_ac5_conflicting_replay_returns_409`;
- `test_ac6_http_race_never_oversells` — 20 потоков с `Barrier(20)` и своими соединениями, Notebook qty 1 → `Counter(statuses) == {201: 3, 409: 17}`, все 409 — `insufficient_stock`, `GET` даёт Notebook 0;
- `test_ac7_internal_error_rolls_back` — триггер из S3 → 500 `internal_error`, stock == SEED, count 0;
- `test_ac8_restart_preserves_state` — POST → `stop_server()` → `start_server()` на том же файле → `GET` показывает списание, повтор → 200 и те же байты, другие данные → 409;
- `test_ac10_busy_database_returns_503` — держатель `BEGIN IMMEDIATE` и `patch(api.BUSY_TIMEOUT_SECONDS, 0.2)` → 503, `retry-after: 1`, count 0; после освобождения → 201;
- `test_ac11_root_page_and_health_unchanged` — `GET /` содержит `Inventory canary` и значения `labels.json`; `GET /health` → `{"ok": true}`.

Проверка: `python3 -m unittest discover -s tests -p 'test_reservations_http.py' -v`.

## S5. `README.md`, `.gitignore` (AC12, D11, D16)

- `.gitignore`: добавить строку `var/`.
- README: дополнить разделами.
  - «Run»: `python3 app.py --host 127.0.0.1 --port 18390 [--db PATH]`; путь по умолчанию `var/inventory.sqlite3`; seed Notebook=3, Pencil=5 создаётся один раз.
  - «API»: `GET /api/items` (quantity = свободный остаток), `POST /api/reservations` (пример тела, таблица статусов SPEC §4, правила идемпотентности; повтор после сетевой ошибки или 503 — с тем же ключом).
  - «Reset»: остановить сервер и удалить `var/inventory.sqlite3` вместе с `var/inventory.sqlite3-journal`; журнал отдельно не удалять.
  - «Rollback»: `git revert`; старый код БД не читает.
  - «Tests»: `python3 -m unittest discover -s tests -v`.

Проверка: `grep -q 'POST /api/reservations' README.md && grep -q 'GET /api/items' README.md && grep -q -- '--db' README.md && grep -q 'inventory.sqlite3-journal' README.md && grep -qx 'var/' .gitignore`.

## S6. Итог Work (AC11)

Закоммитить код, тесты и документацию. Затем: `scripts/agent-check --phase quick`, адресно `-k _ac1_` … `-k _ac12_` по мере надобности (каждый ≤ 20 с), `git diff --quiet 2561257509ca69974ef162cff07d264a98b5553b -- labels.json`, затем `scripts/pipeline-report --task e31339c3-5930-41a1-bfc8-e9d16810e64e` по контракту роли. Полный набор запускает только контроллер (Verify).

## Миграция, восстановление, откат

- Миграция: 0 → 1 при первом старте в одной транзакции (схема, seed, `user_version`). Прерванная миграция не оставляет следов (DDL транзакционен; зонд) и повторяется при следующем старте. Конкурентный старт двух процессов сериализуется `BEGIN IMMEDIATE`; второй видит `user_version = 1`.
- Восстановление: SQLite откатывает незавершённую транзакцию по «горячему» журналу (D8). Повтор клиента с тем же ключом безопасен (D6, D9).
- Откат релиза: D16. Будущие версии схемы: добавлять `MIGRATIONS[n]` и повышать `SCHEMA_VERSION`; старый код отвергает новую схему (AC8).

## Риски и меры

1. WAL-reset bug SQLite ≤ 3.51.2 → режим DELETE, принудительный при старте (D2).
2. Сериализация записей ограничивает пропускную способность. Для синтетики это приемлемо; под длительной блокировкой ответ — 503 с безопасным повтором (D10).
3. Нестабильность тестов гонки → `Barrier`, проверяются счётчики, а не время; `join(timeout)` и явная проверка зависших потоков; очередь сокета 64 (D12).
4. Проверены только Python 3.12.3 и SQLite 3.45.1 (A4) → AC10 и совместимый синтаксис (C5).
5. Ручное удаление журнала повредит восстановление → README (S5).
6. 413 без чтения тела может дать клиенту RST → тесты шлют только заголовки; для синтетики допустимо (SPEC A7).
7. Нехватка диска или прочая ошибка SQLite → ROLLBACK и 500 без частичных записей (AC7).

## Ответы на возражения оппонента

В текущем запросе возражений нет (`request.review = null`, `generation 5`); спор моделей идёт после этого этапа. Заранее закрытые вопросы: WAL против DELETE — D2; DEFERRED против IMMEDIATE (апгрейд чтения до записи даёт SQLITE_BUSY без ожидания) — D5; гонка одинаковых ключей — D6/AC6; потеря ответа после COMMIT — D9; 503 при COMMIT — `_rollback` и повтор (D10); общий объект `Inventory` между потоками безопасен, так как в нём нет соединений (D3).
