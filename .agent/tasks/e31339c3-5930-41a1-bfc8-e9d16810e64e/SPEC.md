# Canary 03 · Резервирование синтетических товаров — спецификация

Architect / Spec. task `e31339c3-5930-41a1-bfc8-e9d16810e64e`, run `c865c4ed-6cba-49a8-92c5-08bc9625a7df`, generation 7,
context_digest `c8648efe008b331f1fcb3692fa67f15e6c2f78f1cff32fd640e0b31fca7097e6`, base `2561257509ca69974ef162cff07d264a98b5553b`.

Источники (поле `content` в `.agent/runtime/e31339c3-5930-41a1-bfc8-e9d16810e64e/context/`): BRIEF `5d011acd….json`; TEAM `18ec0788….json`; ответы владельца `2bb76b98….json` (`stock_semantics` → «Свободный остаток», формат не меняется; `cancellation` → «Нет, только создание»); возражения оппонента gen 6 `5db0d305….json` (+ `DEBATE_FINDINGS.json`, `DEBATE_EVIDENCE.json`); прежние SPEC/PLAN gen 5 `cb0163f4….json`, `a691c886….json`. Зонды архитектора этой генерации — `SPEC_EVIDENCE.json` (ссылки «[E:имя]»). Ответы оппоненту — PLAN.md, последний раздел.

## 1. Исходное состояние

- `app.py`: только `do_GET` (`/health`, `/api/items`, `/`) на `ThreadingHTTPServer` — запросы идут в отдельных потоках, конкуренция реальна.
- `api.py`: `list_items()` возвращает константы Notebook=3, Pencil=5; хранилища нет, поэтому миграция данных = первичное создание БД с теми же значениями.
- `tests/test_api.py`: 2 теста. `.agent/project.json`: quick `python3 -m py_compile app.py api.py`, full `python3 -m unittest discover -s tests -v` (60 с) — реальные проверки, политика не меняется (C3).

## 2. Требования

- **R1.** Остатки в SQLite; первичная инициализация создаёт `1/Notebook/3`, `2/Pencil/5`. `GET /api/items` читает БД; `quantity` — свободный остаток; формат прежний.
- **R2.** `POST /api/reservations` создаёт резервацию (`item_id`, `quantity`, `idempotency_key`) и атомарно уменьшает остаток (контракт — §4). Некорректный запрос, включая неверный `Content-Length` и неполное тело, отклоняется без записи.
- **R3.** Повтор ключа с теми же `item_id`, `quantity` → исходная резервация (200) без повторного списания; тот же ключ с другими данными → 409.
- **R4.** Конкурентные запросы (потоки и процессы на одном файле) не делают остаток отрицательным; списание и запись резервации неделимы.
- **R5.** Сбой внутри операции откатывает транзакцию целиком; неуспешная попытка не занимает ключ.
- **R6.** Данные переживают рестарт и аварийное завершение; повторная инициализация не сбрасывает остатки. Схема версионирована; БД более новой версии отвергается до любого изменения файла (данных, версии, режима журнала).
- **R7.** Автотесты покрывают гонку, rollback, идемпотентность, восстановление и HTTP-контракт; внешних сервисов и настоящих данных нет; UI не меняется.
- **R8.** Занятая БД → повторяемая 503 без записи; путь к БД — `--db`; README описывает контракт, сброс и откат.

## 3. Решения

- **D1. Слои.** `api.py` — хранилище и правила (`Inventory`); `app.py` — только HTTP. Новых модулей нет (C3).
- **D2. Журнал DELETE, `synchronous=FULL`.** WAL отклонён: wal.html описывает WAL-reset bug в SQLite 3.7.0–3.51.2 (исправлен в 3.51.3), локально 3.45.1; параллельное чтение WAL здесь не нужно. Режим меняется только **после** предварительной проверки версии (D7 шаг 2) и только если `PRAGMA journal_mode` без аргумента (чтение) вернул не `delete`: тогда `PRAGMA journal_mode = DELETE`, ответ обязан быть `delete`, иначе `RuntimeError`. Выйти из WAL внутри транзакции нельзя [E:D2_leave_wal_inside_transaction], поэтому смена режима стоит между предварительной проверкой и транзакцией миграции; v1-БД в WAL конвертируется [E:D2_v1_wal_converted_to_delete].
- **D3. Соединение на операцию** через `_connect()`, закрытие в `closing`; соединения между потоками не разделяются. `_connect` ставит только PRAGMA уровня соединения (`foreign_keys`, `synchronous`), в файл они не пишутся.
- **D4. Явные транзакции.** Python ≥ 3.12 (`hasattr(sqlite3, "LEGACY_TRANSACTION_CONTROL")`): `sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS, autocommit=True)`, иначе `isolation_level=None`; только именованные аргументы. Транзакции — только `BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK`; `executescript` (в legacy сначала делает COMMIT) и `with conn:` (не закрывает соединение) запрещены.
- **D5. Сериализация записей.** Резерв — одна транзакция `BEGIN IMMEDIATE`: ключ → товар → остаток → `UPDATE items SET quantity = quantity - ? WHERE id = ? AND quantity >= ?` (`rowcount == 1`) → `INSERT` → чтение строки → `COMMIT`. Защита в глубину: `CHECK (quantity >= 0)`, `UNIQUE (idempotency_key)`.
- **D6. Идемпотентность под блокировкой.** Ключ проверяется в той же транзакции, что и вставка; ключ занимают только успешные резервации. Повтор → 200 с телом, байт в байт равным исходному 201, даже при нулевом остатке. Сравниваются `item_id` и `quantity`; ключ — точно, без нормализации. Ключи бессрочны (A5).
- **D7. Миграции через `PRAGMA user_version`, версия проверяется до изменений.** `SCHEMA_VERSION = 1`. `init_db`: (1) каталог, соединение; (2) **предварительная проверка** — чтение `user_version`; `> SCHEMA_VERSION` → `SchemaVersionError`, файл не изменён [E:D7_future_wal_precheck_read_only: WAL-БД v99 осталась `wal`/99, маркер цел, `-wal`/`-shm` нет]; (3) режим журнала по D2; (4) `BEGIN IMMEDIATE` и **повторное чтение** версии под блокировкой; `>` → ROLLBACK и `SchemaVersionError`; (5) недостающие миграции (DDL и seed транзакционны — зонд gen 5: после ROLLBACK версия 0, таблиц нет), `PRAGMA user_version = <литерал>`, `COMMIT`. Seed только в миграции 0→1 (`INSERT OR IGNORE`). До шага 2 файл может измениться лишь штатным откатом «горячего» журнала SQLite (D8). Остаточное окно 2→3 — A8.
- **D8. Восстановление.** Незафиксированная транзакция упавшего процесса откатывается SQLite по «горячему» журналу при следующем открытии (зонд gen 5: `-journal` 22 016 байт, `os._exit(1)`, затем остатки исходные, `integrity_check = ok`). Зафиксированный резерв виден после `os._exit(0)`.
- **D9. Ответ после COMMIT.** Клиент, потерявший ответ, повторяет с тем же ключом и получает 200.
- **D10. Занятость.** `BUSY_TIMEOUT_SECONDS = 5.0` (читается при `_connect`). `OperationalError` с `sqlite_errorcode & 0xFF in (5, 6)` (без атрибута — подстрока `locked`/`busy`) → `ApiError(503, "storage_busy")` + `Retry-After: 1`; записи нет, повтор безопасен.
- **D11. Путь к БД.** `api.DEFAULT_DB_PATH = Path(__file__).resolve().parent / "var" / "inventory.sqlite3"`; `app.py --db PATH`; `init_db` создаёт каталог; `var/` в `.gitignore`; тесты — только временные каталоги.
- **D12. Сервер.** `InventoryServer(ThreadingHTTPServer)`: `daemon_threads = True`, `request_queue_size = 64`. `make_server(host, port, db_path)` кладёт `Inventory` в `server.inventory`. HTTP/1.0: одно соединение на запрос. Тайм-аут сокета `app.REQUEST_TIMEOUT_SECONDS = 10.0` (читается при каждом соединении): `Handler.setup()` вызывает документированный `self.request.settimeout(...)`, затем `super().setup()`; недокументированный `StreamRequestHandler.timeout` не используется (§7).
- **D13. Валидация payload до открытия БД.** JSON-объект ровно с ключами `item_id`, `quantity`, `idempotency_key`; дубликаты ключей JSON отвергаются (`object_pairs_hook`). `item_id`: `type(v) is int`, 1…2^63−1. `quantity`: `type(v) is int`, 1…1 000 000. `idempotency_key`: `type(v) is str`, `v.strip() != ""`, `len(v) ≤ 128` кодовых точек, `v.encode("utf-8")` без ошибки — это отвергает непарные суррогаты (`"\ud800"` из JSON-escape проходит `json.loads`, но `sqlite3` его не привязывает: `UnicodeEncodeError` [E:D13_lone_surrogates_utf8_encode]). Любой другой Unicode допустим: кириллица, символы вне BMP, в т. ч. корректная пара escape `🧾` → U+1F9FE [E:D13_valid_surrogate_pair_escape], управляющие символы (`a\x00b` хранится и отличается от `a\x00c` и `a` [E:D13_nul_in_key_exact_compare]). `bool` отвергается явно. Нарушение → 400 `invalid_request`.
- **D14. Ошибки** — `{"error": "<code>", "message": "<текст>"}`; контрактен только `error` (A2); трассировки не отдаются.
- **D15. Без отмены и истечения резервов** (решение владельца); GET-эндпоинтов резерваций нет.
- **D16. Откат релиза.** `git revert` коммитов задачи; старый код БД не читает. `var/inventory.sqlite3` можно оставить или удалить вместе с `-journal` при остановленном сервере; журнал отдельно не удалять. Повторный выпуск подхватывает БД v1. Версию кода на одном файле менять только при остановленном сервере.
- **D17. Чтение тела HTTP до `reserve`.** (1) Нет `Content-Length` → 411; заголовок повторён (`headers.get_all`) → 400. (2) Значение после `strip()` — только ASCII-цифры, иначе 400. (3) Ограниченный разбор: ведущие нули отбрасываются; значащих цифр > 4 или число > 4096 → 413, тело не читается; `int()` получает ≤ 4 цифр, поэтому лимит `int_max_str_digits` (4300) недостижим [E:D17_bounded_content_length]. (4) `rfile.read(length)`: `OSError` (включая тайм-аут D12) или `len(body) != length` (EOF раньше срока) → 400, соединение закрывается, `reserve` не вызывается [E:D17_body_read_setup_settimeout]. (5) `decode("utf-8")` → `json.loads`; `UnicodeDecodeError`/`ValueError`/`RecursionError` → 400.

## 4. HTTP-контракт

`GET /api/items` → 200, `Content-Type: application/json`, массив по возрастанию `id` из `{"id": int, "name": str, "quantity": int}`. Свежая БД: ровно `[{"id": 1, "name": "Notebook", "quantity": 3}, {"id": 2, "name": "Pencil", "quantity": 5}]`.

`POST /api/reservations`, тело `{"item_id": 1, "quantity": 2, "idempotency_key": "order-42"}`:

| Ситуация | Статус | `error` |
|---|---|---|
| новая резервация | 201 | — (объект резервации) |
| тот же ключ, те же `item_id`, `quantity` | 200 | — (тот же объект, байт в байт) |
| тот же ключ, другие данные | 409 | `idempotency_key_conflict` |
| остаток < `quantity` | 409 | `insufficient_stock` |
| `item_id` не существует | 404 | `item_not_found` |
| не UTF-8 / не JSON / не объект / лишний, недостающий, дублированный ключ / тип или диапазон / ключ не кодируется в UTF-8 / `Content-Length` не из ASCII-цифр или повторён / тело короче `Content-Length` (EOF или тайм-аут 10 с) | 400 | `invalid_request` |
| нет `Content-Length` | 411 | `length_required` |
| числовой `Content-Length` > 4096 любой длины записи (тело не читается, соединение закрывается) | 413 | `payload_too_large` |
| БД занята дольше `BUSY_TIMEOUT_SECONDS` | 503 + `Retry-After: 1` | `storage_busy` |
| прочая ошибка после ROLLBACK | 500 | `internal_error` |

Порядок: `Content-Length` (наличие, единственность, формат, предел) → полное чтение тела → JSON/D13 → (транзакция) ключ → товар → остаток. Поэтому корректный повтор получает 200 даже при нулевом остатке.

Объект резервации (порядок ключей фиксирован): `{"id", "item_id", "quantity", "idempotency_key", "created_at": "YYYY-MM-DDTHH:MM:SS.mmmZ"}`; `created_at` формирует SQLite (`strftime('%Y-%m-%dT%H:%M:%fZ','now')`, UTC). Ответ — `json.dumps` по умолчанию (не-ASCII → `\uXXXX`), поэтому повтор даёт те же байты.

Прочие маршруты: `GET /api/reservations` → 405 `method_not_allowed` + `Allow: POST`; `POST /api/items` → 405 + `Allow: GET`; прочие POST → 404 `not_found` (JSON). `GET /`, `GET /health` и 404 прочих GET не меняются.

Схема v1:
```sql
CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
  quantity INTEGER NOT NULL CHECK (quantity >= 0));
CREATE TABLE IF NOT EXISTS reservations (id INTEGER PRIMARY KEY AUTOINCREMENT,
  idempotency_key TEXT NOT NULL UNIQUE, item_id INTEGER NOT NULL REFERENCES items(id),
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')));
INSERT OR IGNORE INTO items (id, name, quantity) VALUES (1, 'Notebook', 3), (2, 'Pencil', 5);
```
Инвариант: для каждого товара `seed_quantity == items.quantity + SUM(reservations.quantity)`.

## 5. Ограничения

- **C1.** Только стандартная библиотека Python; сторонних зависимостей, внешних сервисов и настоящих данных нет.
- **C2.** UI не меняется: HTML `/`, `labels.json`, `/health` прежние.
- **C3.** Код только в `app.py` и `api.py` (их компилирует quick); `.agent/project.json` не меняется, `project_policy_change` не объявляется.
- **C4.** Тесты работают только в `tempfile.TemporaryDirectory()` и не трогают `DEFAULT_DB_PATH`.
- **C5.** Синтаксис Python 3.9: без `match` и `X | Y` в аннотациях; `sqlite3.connect` — только именованные аргументы.
- **C6.** БД на локальной ФС (блокировки SQLite на сетевых ФС ненадёжны).
- **C7.** Work/Fix запускают только `scripts/agent-check --phase quick` и адресные тесты `-k _acN_`; полный набор — контроллер в Verify.
- **C8.** Полный набор < 60 с (цель < 20 с); HTTP-вызовы тестов с `timeout=10`.

## 6. Допущения (неблокирующие)

- **A1.** `Content-Type` запроса не проверяется.
- **A2.** Текст `message` не контрактен.
- **A3.** Цель — один процесс сервера; несколько процессов корректны за счёт блокировок SQLite. Гонки проверяются потоками; межпроцессной гонки в автотестах нет (межпроцессные фиксация и откат — AC9).
- **A4.** Реально проверены только Python 3.12.3 и SQLite 3.45.1 (`threadsafety = 3`), 2026-11-08. Python 3.9–3.15 и SQLite ≥ 3.7.11 учтены кодом (D4, C5, D17) и зондом AC10, но не прогонялись.
- **A5.** Ключи бессрочны (D15). **A6.** `quantity` ≤ 1 000 000 достаточно.
- **A7.** Клиент с телом > 4096 байт может получить сброс соединения вместо 413 (тело не читается) — допустимо.
- **A8.** Окно D7 шаг 2→3: процесс *более новой* версии кода мог бы поднять версию WAL-файла между проверкой и сменой режима. Шаг 4 всё равно откажет; последствие — лишь WAL → DELETE без потери данных; одновременная работа двух релизов исключена D16. Закрыть окно полностью нельзя (D2).
- **A9.** `Transfer-Encoding: chunked` не поддерживается: без `Content-Length` → 411. HTTP/1.0 закрывает соединение после ответа, байты сверх длины не становятся новым запросом.
- **A10.** На 3.12.3 JSON из 2000 уровней вложенности (4000 байт) разбирается без `RecursionError` [E:A10_deep_json_nesting]; перехват — защита для других версий, не проверялся.

## 7. Внешние API (stdlib `sqlite3`, `http.server`, SQLite), проверено 2026-11-08

- docs.python.org/3/library/sqlite3.html (3.15.2): `connect(database, *, timeout=5.0, detect_types=0, isolation_level='DEFERRED', check_same_thread=True, factory=..., cached_statements=128, uri=False, autocommit=sqlite3.LEGACY_TRANSACTION_CONTROL)`; в 3.15 параметры кроме `database` keyword-only; `autocommit` с 3.12, умолчание «изменится на False», `isolation_level` действует только в legacy; адаптеры дат устарели с 3.12.
- sqlite.org/lang_transaction.html: «IMMEDIATE causes the database connection to start a new write immediately… might fail with SQLITE_BUSY». sqlite.org/wal.html: WAL персистентен; WAL-reset bug 3.7.0–3.51.2.
- docs.python.org/3/library/stdtypes.html#integer-string-conversion-length-limitation (3.15.2): «The default limit is 4300 digits»; превышение → `ValueError`; «Added in version 3.11», есть в патч-релизах до 3.12 (какие именно — страница не перечисляет, не проверено).
- docs.python.org/3/library/http.server.html (3.15.2): `protocol_version` «defaults to 'HTTP/1.0'»; `close_connection`; `rfile` — `io.BufferedIOBase` (поведение `read(n)` при EOF/тайм-ауте страница не описывает — установлено зондом D17).
- docs.python.org/3/library/socketserver.html (3.15.2): документирован только `BaseServer.timeout`; `StreamRequestHandler.timeout` есть лишь в исходниках → D12 использует `setup()` + `socket.settimeout`.
- Ломающие изменения и меры: умолчание `autocommit` → явный `autocommit=True`; keyword-only 3.15 → именованные аргументы; адаптеры дат → `created_at` в SQL; `int_max_str_digits` → D17(3). Без `RETURNING`/`STRICT`; многострочный `VALUES` требует SQLite ≥ 3.7.11.
- Воспроизводимость: зависимостей нет; Verify/CI — системный `python3` и команды `.agent/project.json`; зонд совместимости — `test_ac10_connection_mode_probe`.

## 8. Критерии приёмки

Имя каждого теста содержит `_acN_`; адресно: `python3 -m unittest discover -s tests -p 'test_*.py' -k _acN_`. «Без записи» = остатки равны seed, `COUNT(*) FROM reservations` = 0, ключ отказа затем даёт 201.

- **AC1 (R1).** Свежая БД: `GET /api/items` → 200, `application/json`, тело как в §4; `list_items()` — уникальные id, `quantity ≥ 0`, новые объекты; после 201 на `{item_id:1, quantity:2}` Notebook = 1.
- **AC2 (R2).** Корректный POST → 201, ключи ровно `id, item_id, quantity, idempotency_key, created_at`, `created_at` ~ `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$`; остаток уменьшен; резерв ровно в остаток успешен, следующий → 409 `insufficient_stock`. Ключи `заказ-№42 ✓` и `🧾-1` (в HTTP — парой escape) → 201, ключ в ответе равен исходному, повтор → 200 с теми же байтами. 405 + `Allow` для `GET /api/reservations` и `POST /api/items`; 404 `not_found` для прочего POST.
- **AC3 (R2).** Сервис: 24 некорректных payload (PLAN S3, вкл. `"\ud800"`, `"x\udc00y"`) → 400 `invalid_request`. `app.parse_content_length` — таблица PLAN S4 (`"9"*5000` → 413, `"0"*5000+"12"` → 12, `"4097"` → 413, нецифровые/повтор → 400, пусто → 411). HTTP: плохие тела и ключ-escape `\ud800` → 400; повторённый `Content-Length` → 400; без него → 411; `5000` и 5000 девяток → 413; сырой сокет, `Content-Length` на 10 больше полного JSON с ключом `partial` + `SHUT_WR` → 400; то же без `SHUT_WR` при `REQUEST_TIMEOUT_SECONDS = 0.5` → 400; неизвестный товар → 404 `item_not_found`; нехватка → 409 `insufficient_stock`. Каждый отказ — без записи.
- **AC4 (R3).** Повтор с теми же данными → 200, тело байт в байт как у 201, списание однократное; работает после исчерпания остатка и после рестарта.
- **AC5 (R3, R5).** Тот же ключ с другим `item_id` или `quantity` → 409 `idempotency_key_conflict` без изменений; ключ отказа 400/404/409 свободен → 201.
- **AC6 (R4).** 30 сервисных потоков и 20 HTTP-запросов (`Barrier`, `quantity=1`, разные ключи, Notebook 3): ровно 3 успеха, остальные 409 `insufficient_stock`, иных ошибок нет, остаток 0, резерваций 3, инвариант §4. 10 запросов с одним ключом (Pencil 2): одна 201, девять 200 с тем же `id`, Pencil 3.
- **AC7 (R5).** Триггер `BEFORE INSERT … RAISE(ABORT, 'injected failure')` после `UPDATE`: `reserve` бросает `sqlite3.IntegrityError`, HTTP → 500 `internal_error`; остатки и резервации прежние, новое соединение не в транзакции; после `DROP TRIGGER` тот же ключ → 201.
- **AC8 (R6).** Новый `Inventory`/сервер на том же файле видит те же данные, повтор → 200 тем же телом; `user_version` = 1, `journal_mode` = `delete`. Будущая схема: (а) DELETE-БД v99 → `SchemaVersionError`, версия и остатки прежние; (б) WAL-БД v99 с `marker`=`keep` → `SchemaVersionError`, затем `wal`, 99, `marker` цел, таблиц `items`/`reservations` нет, `-wal`/`-shm`/`-journal` нет; (в) `api._user_version` с `side_effect=[0, 99]` на новом файле → `SchemaVersionError`, `sqlite_master` пуст, версия 0. v1-БД в WAL → после `Inventory` `delete`, данные прежние.
- **AC9 (R6).** Дочерний процесс (`cache_size = 10`, `BEGIN IMMEDIATE`, `UPDATE … quantity = 0`, 2000 INSERT, `os._exit(1)`) оставляет `-journal`; затем Notebook 3, 0 резерваций, `integrity_check` = `ok`, новый резерв → 201. Резерв дочернего процесса перед `os._exit(0)` виден, повтор → 200.
- **AC10 (R8).** Чужой `BEGIN IMMEDIATE` и `BUSY_TIMEOUT_SECONDS = 0.2`: POST → 503 `storage_busy`, `Retry-After: 1`, без записи; после освобождения → 201. Зонд совместимости: `_connect()` вне транзакции, после `BEGIN IMMEDIATE` — в транзакции; на 3.12+ `autocommit is True`; `sqlite_version_info >= (3, 7, 11)`.
- **AC11 (R7).** `scripts/agent-check --phase quick` проходит; `GET /` содержит `Inventory canary` и значения `labels.json`; `/health` → `{"ok": true}`; `labels.json` не изменён относительно base; в `app.py`/`api.py` только stdlib-импорты.
- **AC12 (R8).** README: оба эндпоинта, статусы, `--db`, сброс (БД и `-journal` вместе при остановленном сервере), откат; `.gitignore` содержит `var/`.

## 9. Вне области

UI, отмена/истечение резервов, список резерваций, аутентификация, `Transfer-Encoding: chunked`, внешние сервисы, изменение `.agent/project.json`, production.
