# Canary 03 · Резервирование синтетических товаров — спецификация

Роль: Architect, стадия Spec. task `e31339c3-5930-41a1-bfc8-e9d16810e64e`, run `0d8e4d63-a66b-496d-abbb-ee3f2763781d`,
generation 5, context_digest `990b7561be21a7787d77379515defa798b2fb3bd498296aca057ce9b9acc57e4`, base `2561257509ca69974ef162cff07d264a98b5553b`.

Источники (поле `content`):
- BRIEF: `.agent/runtime/e31339c3-5930-41a1-bfc8-e9d16810e64e/context/5d011acd4c4ddbd6c52a4b3f0aa18cd2685920f27d94efbc51cdf46bae8b366a.json`
- TEAM (Triage): `.agent/runtime/e31339c3-5930-41a1-bfc8-e9d16810e64e/context/18ec07883ac18ddae8a96a4a997b4aab6af1aef700aef067741e31b79a2cbefd.json`
- Обратная связь «команда выбрана; требуется план архитектора»: `.agent/runtime/e31339c3-5930-41a1-bfc8-e9d16810e64e/context/ad528fb6275b1b161e4f9dba6a523c42124d2902cde914145eeb10895f60ab44.json`
- Ответы владельца получены в этой сессии через `ask_user_question` (Kandev, session `b9369b74-b00c-4c73-8b4d-672533ffd476`); в `request.owner_answers` их нет (null):
  - «Что показывает GET /api/items после резерва» → **свободный остаток, формат не меняется** (рекомендованный вариант);
  - «Нужна ли отмена/истечение резервов» → **нет, только создание** (рекомендованный вариант).

Документ заменяет предварительный SPEC Triage. Все «открытые вопросы для planner» из Triage закрыты решениями D1–D16.

## 1. Исходное состояние (доказательства)

- `app.py`: `Handler` реализует только `do_GET` (`/health`, `/api/items`, `/`); сервер `ThreadingHTTPServer` — каждый запрос в отдельном потоке, т. е. конкурентные запросы реальны.
- `api.py`: `list_items()` возвращает константы `Notebook=3`, `Pencil=5`; хранилища и операций записи нет. Сохранённого состояния нет — миграция данных сводится к первичному созданию БД с теми же значениями.
- `tests/test_api.py`: 2 теста (уникальность id/неотрицательность, свежие копии значений).
- `.agent/project.json`: quick = `python3 -m py_compile app.py api.py`; full = `python3 -m unittest discover -s tests -v` (таймаут 60 с). Проверки реальные, не заглушки; политика не меняется (C3).

## 2. Требования

- **R1.** Остатки хранятся в SQLite. Первичная инициализация создаёт товары `1/Notebook/3` и `2/Pencil/5`. `GET /api/items` читает их из БД; `quantity` — свободный остаток после всех резервов; формат ответа прежний.
- **R2.** `POST /api/reservations` создаёт резервацию из `item_id`, `quantity`, `idempotency_key` и атомарно уменьшает остаток. Контракт статусов и тел — раздел 4. Некорректный запрос отклоняется без записи в БД.
- **R3.** Идемпотентность: повтор ключа с теми же `item_id` и `quantity` возвращает исходную резервацию (200) без повторного списания. Тот же ключ с другими данными — 409.
- **R4.** Конкурентные запросы (потоки и процессы на одном файле БД) никогда не делают остаток отрицательным. Списание и запись резервации неделимы.
- **R5.** Любой сбой внутри операции откатывает транзакцию целиком. Неуспешная попытка не занимает ключ.
- **R6.** Данные переживают рестарт и аварийное завершение процесса. Повторная инициализация не сбрасывает остатки. Схема версионирована; БД более новой версии отвергается без изменений.
- **R7.** Автотесты покрывают гонку, rollback, идемпотентность, восстановление и HTTP-контракт. Внешних сервисов и настоящих данных нет; UI не меняется.
- **R8.** Эксплуатация: занятая БД даёт повторяемую 503 без записи; путь к БД задаётся `--db`. README описывает контракт, сброс данных и откат.

## 3. Решения

- **D1. Слои.** `api.py` — хранилище и бизнес-правила (класс `Inventory`). `app.py` — только HTTP (маршруты, чтение тела, JSON, коды). Новых модулей нет (C3).
- **D2. SQLite, режим журнала DELETE (rollback journal), `synchronous=FULL`.** WAL отклонён. На wal.html описан WAL-reset bug в SQLite 3.7.0–3.51.2 (исправлен в 3.51.3, 2026-03-13); он проявляется при одновременной записи/checkpoint нескольких соединений, а локальная SQLite 3.45.1 в этом диапазоне. Параллельное чтение WAL для этого масштаба не нужно. `init_db` при каждом старте выполняет `PRAGMA journal_mode = DELETE` и проверяет, что вернулось `delete`; так файл, когда-то переведённый в WAL, возвращается в DELETE.
- **D3. Соединение на операцию.** Каждый вызов открывает своё соединение через `_connect()` и закрывает его в `finally`/`contextlib.closing`. Соединения между потоками не разделяются.
- **D4. Явное управление транзакциями.** На Python ≥ 3.12 (`hasattr(sqlite3, "LEGACY_TRANSACTION_CONTROL")`) используется `sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS, autocommit=True)`, иначе — `isolation_level=None`. Только именованные аргументы. Транзакции открываются только SQL-командой `BEGIN IMMEDIATE`, закрываются `COMMIT`/`ROLLBACK`. `executescript` и `with conn:` запрещены: в legacy-режиме `executescript` сначала делает COMMIT, а `with conn` не закрывает соединение.
- **D5. Сериализация записей.** Вся логика резерва — внутри одной транзакции `BEGIN IMMEDIATE`, которая сразу берёт блокировку записи. Порядок: (1) поиск ключа → (2) поиск товара → (3) проверка остатка → (4) `UPDATE items SET quantity = quantity - ? WHERE id = ? AND quantity >= ?` с проверкой `rowcount == 1` → (5) `INSERT` резервации → (6) чтение вставленной строки → `COMMIT`. Защита в глубину: `CHECK (quantity >= 0)` на `items`, `UNIQUE` на `idempotency_key`.
- **D6. Идемпотентность внутри блокировки.** Ключ проверяется в той же транзакции, что и вставка (без TOCTOU). Ключ занимают только успешные резервации. Повтор возвращает 200 с телом, байт в байт равным исходному 201, даже если остаток уже исчерпан. Сравниваются `item_id` и `quantity`; ключ сравнивается точно (регистр, пробелы, без нормализации). Ключи хранятся бессрочно (A5).
- **D7. Миграции через `PRAGMA user_version`.** `SCHEMA_VERSION = 1`. `init_db` в одной транзакции `BEGIN IMMEDIATE` читает `user_version`, применяет недостающие миграции (DDL и seed в SQLite транзакционны; проверено зондом: после ROLLBACK `user_version=0` и таблиц нет), затем выполняет `PRAGMA user_version = 1` (подставляется литерал: PRAGMA не принимает параметры) и `COMMIT`. Seed выполняется только в миграции 0→1 (`INSERT OR IGNORE`), поэтому рестарт не сбрасывает остатки. Если `user_version > SCHEMA_VERSION`, бросается `SchemaVersionError` без изменений.
- **D8. Восстановление.** Незафиксированная транзакция упавшего процесса откатывается SQLite по «горячему» журналу при следующем открытии. Зонд: изменения ушли на диск (`-journal` 22 016 байт), процесс завершён `os._exit(1)`, после открытия остатки исходные, `integrity_check = ok`, журнал удалён. Зафиксированная (COMMIT) резервация видна после `os._exit(0)`.
- **D9. Ответ клиенту после COMMIT.** Если клиент отвалился после фиксации, он повторяет запрос с тем же ключом и получает 200 с той же резервацией.
- **D10. Занятость.** `BUSY_TIMEOUT_SECONDS = 5.0` (модульная константа, читается в момент вызова `_connect`). `sqlite3.OperationalError` с кодом SQLITE_BUSY/SQLITE_LOCKED (`exc.sqlite_errorcode & 0xFF in (5, 6)`, при отсутствии атрибута — подстрока `"locked"`/`"busy"` в сообщении) → `ApiError(503, "storage_busy")`, заголовок `Retry-After: 1`. Записи нет; повтор с тем же ключом безопасен.
- **D11. Путь к БД.** `api.DEFAULT_DB_PATH = Path(__file__).resolve().parent / "var" / "inventory.sqlite3"`; CLI `app.py --db PATH` (по умолчанию `DEFAULT_DB_PATH`). `init_db` создаёт родительский каталог. `var/` в `.gitignore`. Тесты всегда используют временный каталог.
- **D12. Сервер.** `class InventoryServer(ThreadingHTTPServer)` с `daemon_threads = True` и `request_queue_size = 64` (по умолчанию 5 — мало для теста гонки). `make_server(host, port, db_path)` создаёт `Inventory` и кладёт его в `server.inventory`; обработчик берёт `self.server.inventory`. Протокол — HTTP/1.0 по умолчанию: одно соединение на запрос.
- **D13. Валидация до транзакции.** Тело ≤ 4096 байт, UTF-8, JSON-объект ровно с ключами `item_id`, `quantity`, `idempotency_key`. Дубликаты ключей JSON отклоняются (`object_pairs_hook`). `item_id`: `type(v) is int`, 1 ≤ v ≤ 2^63−1. `quantity`: `type(v) is int`, 1 ≤ v ≤ 1 000 000. `idempotency_key`: `type(v) is str`, `v.strip() != ""`, `len(v) ≤ 128`. `bool` отвергается явно, поскольку `isinstance(True, int)` истинно.
- **D14. Формат ошибок.** `{"error": "<code>", "message": "<текст>"}`. Контрактен только `error`; `message` — для людей (A2). Трассировки клиенту не отдаются.
- **D15. Без отмены и истечения резервов** — решение владельца. Новых GET-эндпоинтов резерваций нет.
- **D16. Откат релиза.** `git revert` коммитов задачи: старый код БД не читает. Файл `var/inventory.sqlite3` можно оставить или удалить вместе с `var/inventory.sqlite3-journal` при остановленном сервере. Журнал отдельно не удалять — он нужен для восстановления. Повторный выпуск подхватывает существующую БД v1 без потерь.

## 4. HTTP-контракт

`GET /api/items` → `200`, `Content-Type: application/json`, массив по возрастанию `id`: `{"id": int, "name": str, "quantity": int}`. Свежая БД — ровно `[{"id": 1, "name": "Notebook", "quantity": 3}, {"id": 2, "name": "Pencil", "quantity": 5}]`.

`POST /api/reservations`, тело `{"item_id": 1, "quantity": 2, "idempotency_key": "order-42"}`:

| Ситуация | Статус | Тело (`error`) |
|---|---|---|
| новая резервация | 201 | объект резервации |
| тот же ключ и те же `item_id`, `quantity` | 200 | тот же объект, байт в байт |
| тот же ключ, другие данные | 409 | `idempotency_key_conflict` |
| остаток < `quantity` | 409 | `insufficient_stock` |
| `item_id` не существует | 404 | `item_not_found` |
| не UTF-8 / не JSON / не объект / лишний, недостающий или дублированный ключ / неверный тип или диапазон / неверный `Content-Length` | 400 | `invalid_request` |
| нет `Content-Length` | 411 | `length_required` |
| `Content-Length` > 4096 (тело не читается, соединение закрывается) | 413 | `payload_too_large` |
| БД занята дольше `BUSY_TIMEOUT_SECONDS` | 503 + `Retry-After: 1` | `storage_busy` |
| прочая ошибка (SQLite, сбой) после ROLLBACK | 500 | `internal_error` |

Порядок проверок: длина → JSON/валидация → (транзакция) ключ → товар → остаток. Корректный повтор поэтому получает 200 даже при нулевом остатке.

Объект резервации (порядок ключей фиксирован): `{"id": int, "item_id": int, "quantity": int, "idempotency_key": str, "created_at": "YYYY-MM-DDTHH:MM:SS.mmmZ"}`. `created_at` формирует SQLite: `strftime('%Y-%m-%dT%H:%M:%fZ','now')`, UTC; адаптеры дат Python не используются.

Прочие маршруты: `GET /api/reservations` → 405 `method_not_allowed`, `Allow: POST`. `POST /api/items` → 405 `method_not_allowed`, `Allow: GET`. Прочие POST → 404 `not_found` (JSON). `GET /`, `GET /health` и 404 для прочих GET не меняются.

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

- **C1.** Только стандартная библиотека Python (`http.server`, `sqlite3`, `json`, `threading`, `unittest`, `subprocess`, `tempfile`). Сторонних зависимостей, внешних сервисов и настоящих данных нет.
- **C2.** UI не меняется: HTML `/`, `labels.json`, `/health` прежние.
- **C3.** Код только в `app.py` и `api.py` — их компилирует quick-проверка. `.agent/project.json` не меняется (`project_policy_change` не объявляется).
- **C4.** Тесты работают только с `tempfile.TemporaryDirectory()` и никогда не трогают `DEFAULT_DB_PATH`.
- **C5.** Синтаксис совместим с Python 3.9: без `match`, без `X | Y` в аннотациях. `sqlite3.connect` — только с именованными аргументами.
- **C6.** БД на локальной ФС; блокировки SQLite на сетевых ФС ненадёжны.
- **C7.** Work/Fix запускают только `scripts/agent-check --phase quick` и адресные тесты (`-k _acN_`). Полный набор — только контроллер в Verify.
- **C8.** Полный набор укладывается в таймаут 60 с; цель — менее 20 с, каждый HTTP-вызов в тестах с `timeout=10`.

## 6. Допущения (неблокирующие)

- **A1.** `Content-Type` запроса не проверяется; тело всегда разбирается как JSON.
- **A2.** Текст `message` не входит в контракт.
- **A3.** Цель — один процесс сервера. Несколько процессов на одном файле корректны за счёт блокировок SQLite, но отдельно не оптимизируются.
- **A4.** Реально проверены только Python 3.12.3 и SQLite 3.45.1 (`sqlite3.threadsafety = 3`), зонды от 2026-11-08. Совместимость с Python 3.9–3.15 и SQLite ≥ 3.7.11 обеспечена кодом (D4, C5) и проверкой совместимости AC10, но на этих версиях не прогонялась.
- **A5.** Ключи идемпотентности бессрочны (резервы постоянны, D15).
- **A6.** Значений `quantity` ≤ 1 000 000 достаточно для синтетических данных.
- **A7.** Клиент, отправивший тело > 4096 байт, может получить сброс соединения вместо чтения 413: сервер такое тело не читает. Для синтетического сервиса это допустимо.

## 7. Внешняя API-интеграция (stdlib `sqlite3` + SQLite), проверено 2026-11-08

- https://docs.python.org/3/library/sqlite3.html (страница Python 3.15.2): `connect(database, *, timeout=5.0, detect_types=0, isolation_level='DEFERRED', check_same_thread=True, factory=..., cached_statements=128, uri=False, autocommit=sqlite3.LEGACY_TRANSACTION_CONTROL)`. В 3.15 все параметры, кроме `database`, стали keyword-only. `autocommit` появился в 3.12; значение по умолчанию «изменится на False в будущем релизе», а `isolation_level` действует только при legacy. `timeout` по умолчанию 5 с. Стандартные адаптеры дат устарели с 3.12. `check_same_thread=True` по умолчанию.
- https://www.sqlite.org/lang_transaction.html: «IMMEDIATE causes the database connection to start a new write immediately… might fail with SQLITE_BUSY if another write transaction is already active».
- https://www.sqlite.org/wal.html: WAL-режим персистентен; WAL-reset bug в 3.7.0–3.51.2, исправлен в 3.51.3.
- Ломающие изменения и меры: смена умолчания `autocommit` → явный `autocommit=True` (D4); keyword-only в 3.15 → только именованные аргументы; устаревшие адаптеры → `created_at` формирует SQL. Используемые возможности SQLite (многострочный `VALUES` ≥ 3.7.11, `CHECK`, `AUTOINCREMENT`, `strftime('%f')`) без `RETURNING`/`STRICT`.
- Воспроизводимая установка: зависимостей нет, Verify/CI используют системный `python3` и команды из `.agent/project.json`. Проверка совместимости — тест `test_ac10_connection_mode_probe` (AC10).

## 8. Критерии приёмки

Каждый тест содержит в имени `_acN_`; адресная проверка: `python3 -m unittest discover -s tests -p 'test_*.py' -k _acN_`.

- **AC1 (R1).** На свежей БД `GET /api/items` → 200, `application/json`, тело ровно как в разделе 4. `Inventory.list_items()` возвращает уникальные id, `quantity ≥ 0` и новые объекты при каждом вызове. После 201 на `{item_id:1, quantity:2}` Notebook = 1.
- **AC2 (R2).** Корректный POST → 201, тело ровно с ключами `id, item_id, quantity, idempotency_key, created_at`, причём `created_at` соответствует `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$`. Остаток уменьшен на `quantity`; резерв ровно в остаток (3 Notebook) успешен, следующий даёт 409 `insufficient_stock`. 405 и `Allow` для `GET /api/reservations` и `POST /api/items`; 404 `not_found` для прочего POST.
- **AC3 (R2).** Каждый некорректный ввод из таблицы теста (не менее 16 случаев D13) → 400 `invalid_request`. Неизвестный товар → 404 `item_not_found`; `quantity` > остатка → 409 `insufficient_stock`; без `Content-Length` → 411; `Content-Length: 5000` → 413. После каждого отказа остатки не изменились и `COUNT(*) FROM reservations` = 0.
- **AC4 (R3).** Повтор ключа с теми же данными → 200, тело байт в байт равно исходному 201, списание однократное, резервация одна. Повтор работает и после исчерпания остатка, и после рестарта сервера.
- **AC5 (R3, R5).** Тот же ключ с другим `item_id` или `quantity` → 409 `idempotency_key_conflict` без изменений. Ключ отклонённой попытки (400/404/409 по остатку) свободен: следующий корректный запрос с ним → 201.
- **AC6 (R4).** Гонки. 30 потоков на сервисном уровне и 20 HTTP-запросов (`threading.Barrier`, `quantity=1`, разные ключи, Notebook = 3): ровно 3 успеха, остальные 409 `insufficient_stock`, других ошибок 0, итоговый остаток 0, резерваций 3, инвариант раздела 4 выполняется. 10 конкурентных запросов с одним ключом (Pencil, 2): одна 201, девять 200 с тем же `id`, Pencil = 3.
- **AC7 (R5).** Сбой после `UPDATE`: триггер `BEFORE INSERT ON reservations … RAISE(ABORT, 'injected failure')`. `reserve` бросает `sqlite3.IntegrityError`, HTTP отвечает 500 `internal_error`. Остатки и число резерваций не изменились, у нового соединения `in_transaction` = False. После удаления триггера тот же ключ даёт 201.
- **AC8 (R6).** После резерва новый `Inventory`/новый сервер на том же файле показывает те же остатки и резервации; повтор → 200 с тем же телом. `PRAGMA user_version` = 1, `PRAGMA journal_mode` = `delete`. На БД с `user_version = 99` `Inventory(...)` бросает `SchemaVersionError`, `user_version` и данные не тронуты.
- **AC9 (R6).** Дочерний процесс (`cache_size = 10`, `BEGIN IMMEDIATE`, `UPDATE items SET quantity = 0 WHERE id = 1`, 2000 INSERT с ключами `crash-NNNNN-…`, `os._exit(1)`) оставляет файл `-journal`. Родитель затем видит Notebook = 3, 0 резерваций, `integrity_check` = `ok`, и новый резерв → 201. Резерв, сделанный дочерним процессом перед `os._exit(0)`, виден родителю, а повтор → 200.
- **AC10 (R8).** Чужое соединение держит `BEGIN IMMEDIATE`, `api.BUSY_TIMEOUT_SECONDS` подменён на 0.2: POST → 503 `storage_busy`, `Retry-After: 1`, без записи. После снятия блокировки тот же ключ → 201. Проверка совместимости: соединение `_connect()` не в транзакции, после `BEGIN IMMEDIATE` — в транзакции; на 3.12+ `conn.autocommit is True`; `sqlite3.sqlite_version_info >= (3, 7, 11)`.
- **AC11 (R7).** `scripts/agent-check --phase quick` проходит. `GET /` содержит `Inventory canary` и значения `labels.json`, `GET /health` → `{"ok": true}`. `labels.json` не изменён относительно base. В `app.py`/`api.py` только импорты стандартной библиотеки.
- **AC12 (R8).** README описывает оба эндпоинта, таблицу статусов, `--db`, сброс данных (удалять файл БД и `-journal` вместе при остановленном сервере), откат; `.gitignore` содержит строку `var/`.

## 9. Вне области

UI, отмена/истечение резервов, список резерваций, аутентификация, внешние сервисы, изменение `.agent/project.json`, production.
