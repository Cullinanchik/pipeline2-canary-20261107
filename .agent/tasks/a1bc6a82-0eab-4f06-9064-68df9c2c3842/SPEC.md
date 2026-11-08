# Canary 02 · Фильтрация синтетического каталога — ТЗ архитектора

Задача `a1bc6a82-0eab-4f06-9064-68df9c2c3842` · run `bf001757-2c27-4a3e-b64b-ca755fe89097` ·
generation `2` · context_digest `1194a1e049737c76d697b0371c05473f93f1fadc3d7bcdd243ad3f1ab00dba0b` · base `57923dcefab1b47115a9bab26b4a73b8e879f19b`.

## 1. Цель и источники

Добавить в синтетический inventory API фильтр `GET /api/items?min_quantity=N`. Прежний ответ без
параметра сохраняется байт в байт. Неверный параметр даёт HTTP 400 с понятной JSON-ошибкой.

Входные данные (контроллер, текущий запрос):
- brief: `.agent/runtime/a1bc6a82-0eab-4f06-9064-68df9c2c3842/context/385402fc1290d867c7595e64b9cf5d01c0ef8b3a84a143d8125597771c97aa71.json` (поле `content`);
- оценка Triage (TEAM.json): `.agent/runtime/a1bc6a82-0eab-4f06-9064-68df9c2c3842/context/6cb4c1b74a0a75bc3588e8a27ccadb2e61acfb89c603cbb5110754edbb2508c5.json`;
- обратная связь run: `.agent/runtime/a1bc6a82-0eab-4f06-9064-68df9c2c3842/context/ad528fb6275b1b161e4f9dba6a523c42124d2902cde914145eeb10895f60ab44.json` («команда выбрана; требуется план архитектора»);
- `request.owner_answers`, `request.review`, `request.checks`, `request.lessons` — `null`. Возражений оппонента в текущем запросе нет; ответы на ожидаемые возражения — раздел 9.

Ответы владельца получены в этой сессии (`75a8c0aa-b8c0-47f5-8f76-f1a7340ee42d`) через ask_user_question,
2026-11-08:
- `error_language` → «Английский (рекомендую)»: текст ошибок пишется по-английски, машинный код латиницей;
- `unknown_params` → «Игнорировать (рекомендую)»: посторонние параметры и опечатки не учитываются.

Это ответы на продуктовые вопросы, а не согласование плана. Согласование проводит контроллер отдельно.

## 2. Текущее состояние (доказательства из кода на base)

- `api.py:2-3`: `list_items()` при каждом вызове строит новый список
  `[{"id": 1, "name": "Notebook", "quantity": 3}, {"id": 2, "name": "Pencil", "quantity": 5}]`.
- `app.py:12`: `path = urlsplit(self.path).path` — query не разбирается; `/api/items` всегда отдаёт
  `200`, `Content-Type: application/json`, тело `json.dumps(list_items()).encode()` (`app.py:16`).
  `self.send_response(200)` зашит в `app.py:26`, пути для 400 нет.
- `tests/test_api.py`: класс `InventoryTests` проверяет уникальность id, `quantity >= 0` и свежесть.
  HTTP не проверяется.
- `.agent/project.json`: quick-проверка `python3 -m py_compile app.py api.py`, обязательная проверка
  `python3 -m unittest discover -s tests -v`. CI (`.github/workflows/ci.yml`) запускает ту же команду.
  Это настоящие проверки, а не заглушки.

Корневые риски, подтверждённые пробой на CPython 3.12.3 (2026-11-08, вне репозитория):
1. `parse_qs` без `keep_blank_values=True` отбрасывает `min_quantity=` и голое `min_quantity`.
   Пустое значение тогда молча вернуло бы полный каталог.
2. `int()` принимает `" 1"`, `"+1"`, `"1_000"`, `"١"` (арабско-индийская цифра) и `"1\n"`.
   `str.isdigit()` и `\d` пропускают Unicode-цифры, `re.match(r"[0-9]+$")` пропускает `"1\n"`.
3. `int()` строки длиннее 4300 цифр, включая ведущие нули, бросает `ValueError`.
4. Любое необработанное исключение в `do_GET` закрывает соединение без HTTP-ответа: клиент получает
   `RemoteDisconnected`. Проверено пробой. Поэтому все ошибки разбора должны превращаться в 400.
5. `+` в query декодируется как пробел (`min_quantity=+1` → `" 1"`). `;` с Python 3.10 не разделяет
   параметры (`min_quantity=1;min_quantity=2` → одно значение `"1;min_quantity=2"`). `min%5Fquantity`
   декодируется в имя `min_quantity`.

## 3. Требования (R*)

- **R1. Совместимость без фильтра.** Если имени `min_quantity` нет в query, `GET /api/items` отвечает
  `200`, `Content-Type: application/json`, тело байт в байт равно `json.dumps(list_items()).encode()`.
  Это же правило действует для `/api/items?` и для query только из посторонних параметров.
- **R2. Фильтрация.** При допустимом целом N в ответе остаются только товары с `quantity >= N`
  (граница включена). Порядок каталога и все поля товара сохраняются. `N=0` возвращает все товары,
  N больше максимального остатка — `[]` (HTTP 200).
- **R3. Допустимая запись N.** Значение после стандартного URL-декодирования должно состоять только из
  ASCII-цифр `0-9`, минимум одной. Ведущие нули допускаются (`007` = 7, `00` = 0). Диапазон:
  `0 ≤ N ≤ 9223372036854775807` (2^63−1). Округления, обрезки, `strip()` и знака `+` нет.
- **R4. Ошибки.** Повтор имени, пустое, отрицательное, дробное, слишком большое или иное нечисловое
  значение дают `400`, `Content-Type: application/json` и тело
  `{"error": {"code": <code>, "parameter": "min_quantity", "message": <message>}}` с кодом и текстом
  из таблицы раздела 5. Полученное значение в ответе не повторяется. Приложение не падает и не рвёт
  соединение ни на каком query.
- **R5. Посторонние параметры** (ответ владельца) игнорируются: `min_qty=3`, `MIN_QUANTITY=3`, `foo=1`,
  `=5`. Имя `min_quantity` чувствительно к регистру. Посторонние параметры рядом с `min_quantity` не
  мешают фильтру.
- **R6. Неизменность.** Данные `list_items()`, свежесть возвращаемых значений (новые объекты при каждом
  вызове), UI `/`, `/health`, ответы 404 (в т. ч. `/api/items/`) и `labels.json` не меняются. На
  маршрутах, кроме `/api/items`, параметр `min_quantity` не действует.
- **R7. Автопроверки.** В `tests/test_api.py` добавлены тесты чистых функций (`filter_items`,
  `parse_min_quantity`, `MinQuantityError`), HTTP-тесты на реальном `ThreadingHTTPServer` и проба
  совместимости семантики `parse_qs`. Политика проверок (`.agent/project.json`, CI) не меняется.

## 4. Решения (D*)

- **D1. Разбор query — чистая функция в `api.py`.** `parse_min_quantity(query: str) -> int | None`
  принимает сырую строку `urlsplit(path).query` и сама вызывает
  `parse_qs(query, keep_blank_values=True)`. Так все граничные случаи проверяются без HTTP, а
  `app.py` остаётся тонким. Отклонено: разбор в `app.py` (не тестируется как чистая функция) и
  `parse_qsl`/ручной split (дублирует стандартное декодирование `%XX` и `+`).
- **D2. Фильтр — отдельная чистая функция** `filter_items(items, min_quantity)`. Возвращает новый список
  `[item for item in items if item["quantity"] >= min_quantity]` и не мутирует вход. `list_items()`
  остаётся без изменений: сигнатура, тело и данные те же. Это гарантирует R1 и R6. Отклонено:
  параметр `list_items(min_quantity=None)` — меняет функцию данных, которую brief велит не трогать.
- **D3. Валидация — полное совпадение регулярного выражения** `re.compile(r"[0-9]+").fullmatch(raw)`.
  Не используются `int()` напрямую, `isdigit()`, `\d` и `re.match(...$)`: см. риски 2 и 3 раздела 2.
- **D4. Верхняя граница 2^63−1** (`MAX_MIN_QUANTITY = 9223372036854775807`), принятый в JSON/БД
  диапазон int64. Перед `int()` ведущие нули отбрасываются (`raw.lstrip("0") or "0"`), длина значимой
  части проверяется (`> 19` → `too_large`). Поэтому `int()` никогда не получает больше 19 цифр, и
  предел 4300 цифр недостижим. Значения от максимального остатка до 2^63−1 допустимы и дают `[]`.
- **D5. Порядок классификации одного значения:** повтор → пусто → цифры (диапазон) → отрицательное
  (`-0*[1-9][0-9]*`) → дробное (`[+-]?(?:[0-9]+\.[0-9]*|\.[0-9]+)`) → прочее `invalid`. Повтор
  проверяется до значений: `min_quantity=3&min_quantity=3` — тоже ошибка. `-0` и `-00` — `invalid`,
  а не `negative`: численно это не отрицательное число, но запись не из одних цифр.
- **D6. Ошибка — исключение `MinQuantityError(ValueError)`** с атрибутами `code`, `message` и методом
  `to_dict()`. Тексты берутся из словаря `MIN_QUANTITY_ERRORS`. Обработчик ловит только
  `MinQuantityError`, остальные ошибки не маскируются.
- **D7. HTTP:** в `app.py` появляется переменная `status = 200`. Ветка `/api/items` выставляет
  `status = 400` при ошибке. Заголовки (`Content-Type: application/json`, `Content-Length`) отправляет
  прежний общий путь. Ветки `/`, `/health` и 404 не меняются.
- **D8. Тексты ошибок на английском** (ответ владельца `error_language`), коды стабильны (раздел 5).
- **D9. Посторонние параметры игнорируются** (ответ владельца `unknown_params`), как в текущем коде.
- **D10. HTTP-тесты** поднимают `ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)` на эфемерном
  порту в фоновом потоке и обращаются через `http.client`. Это не пересекается с портами превью
  18390–18399. `QuietHandler` переопределяет `log_message` только в тестах.
- **D11. Политика проверок не меняется** (`project_policy_change` не нужен): quick `py_compile` и полный
  `unittest discover` уже реальные и покрывают новый код. `tests/test_api.py` компилируется при
  запуске unittest в Verify, дополнительно — точечным `py_compile` у исполнителя.
- **D12. Откат** — `git revert` коммита реализации. Данных, миграций и состояния нет, откат мгновенный
  и полный. Восстановление после сбоя не требуется: обработчик без состояния, ошибки разбора дают 400.

## 5. Контракт ошибок (точные строки)

| code | Когда (после URL-декодирования) | message |
|---|---|---|
| `duplicate` | имя `min_quantity` встречается ≥ 2 раз (в т. ч. `min%5Fquantity`) | `min_quantity must be specified at most once` |
| `empty` | `min_quantity=` или `min_quantity` без `=` | `min_quantity must not be empty` |
| `too_large` | только цифры, но значение > 9223372036854775807 | `min_quantity must not exceed 9223372036854775807` |
| `negative` | `-` и цифры, значение ≠ 0 (`-1`, `-05`) | `min_quantity must not be negative` |
| `not_integer` | десятичная дробь (`2.5`, `3.0`, `.5`, `5.`, `-2.5`, `+2.5`) | `min_quantity must be a whole number` |
| `invalid` | всё прочее (`abc`, `+1`, ` 1`, `1e3`, `١`, `²`, `1\n`, `1_000`, `0x10`, `-0`, `%FF`, `1;min_quantity=2`) | `min_quantity must be a non-negative integer written with digits 0-9` |

Тело: `json.dumps({"error": {"code": code, "parameter": "min_quantity", "message": message}}).encode()`.
Статус 400, `Content-Type: application/json`, `Content-Length` равен длине тела.

## 6. Ограничения (C*)

- **C1.** Меняются только `api.py`, `app.py`, `tests/test_api.py` и документы задачи. Не меняются
  `labels.json`, `README.md`, `.agent/project.json`, `.github/`, `notes/`.
- **C2.** Только стандартная библиотека Python, без новых зависимостей и файлов зависимостей.
- **C3.** Поддерживаемая версия — CPython ≥ 3.10 (поведение `separator='&'` в `parse_qs`). Проверено на
  3.12.3 (хост Verify). Аннотации типов с `|` и `list[...]` в коде не используются.
- **C4.** Агенты не запускают полный набор тестов. Исполнитель — только `scripts/agent-check --phase quick`,
  `py_compile` и именованные тесты `-k`. Полный набор запускает контроллер в Verify.
- **C5.** Не логировать и не возвращать сырое значение параметра: оно может быть длиной до ~64 КБ
  (предел строки запроса `http.server`).
- **C6.** Без push, merge, переходов задачи и согласований: этим владеет контроллер.

## 7. Допущения (A*)

- **A1.** CI `ubuntu-latest` использует системный `python3` ≥ 3.10. Конкретную версию образа на
  2026-11-08 в этой сессии проверить нельзя. Проба совместимости (AC9) упадёт явно, если семантика
  `parse_qs` иная.
- **A2.** Клиентов, зависящих от посторонних параметров или текущих 200 на неверный `min_quantity`, нет:
  данные синтетические, параметр новый.
- **A3.** Ведущие нули (`007`) и верхняя граница 2^63−1 — техническое решение архитектора (владелец
  уведомлён в вопросе). Сменить их можно правкой одной константы и одного регулярного выражения.
- **A4.** Метод `HEAD` и прочие методы остаются как есть (501 от `BaseHTTPRequestHandler`). Задача их не касается.

## 8. Критерии приёмки (AC*)

Команды запускаются из корня репозитория. `T` = `python3 -m unittest discover -s tests -p test_api.py`.

- **AC1 (R1).** `/api/items` и `/api/items?` → 200, `application/json`, тело ==
  `json.dumps(list_items()).encode()` и == литералу двух товаров. Проверка:
  `T -k CatalogHTTPTests.test_no_filter_returns_full_catalog`.
- **AC2 (R2).** `filter_items` на выборке с остатками `[0, 2, 3, 3, 10]`: порог 3 → id `[3, 4, 5]`,
  0 → все, 11 и 2^63−1 → `[]`, пустой вход → `[]`. Вход не мутирован, результат — новый список.
  Свежесть: изменение результата не влияет на следующий вызов. Проверка: `T -k FilterItemsTests`.
- **AC3 (R2).** HTTP: `min_quantity` = `0`/`3` → id `[1, 2]`, `4`/`5`/`004` → `[2]`, `6` и
  `9223372036854775807` → `[]`. Все ответы 200 `application/json`, тело при `0` == полному каталогу.
  Проверка: `T -k CatalogHTTPTests.test_filter_results`.
- **AC4 (R3).** `parse_min_quantity`: `0`→0, `00`→0, `3`→3, `007`→7, `9223372036854775807`→2^63−1,
  `"0"*5000+"1"`→1, `min_quantity=4&foo=bar`→4, `foo=&min_quantity=4`→4, `min%5Fquantity=4`→4.
  Проверка: `T -k ParseMinQuantityTests.test_valid_values`.
- **AC5 (R4).** `parse_min_quantity` бросает `MinQuantityError` с кодом из таблицы раздела 5 для всех 32
  случаев PLAN.md (шаг S3), включая `"1"+"0"*5000` → `too_large` без `ValueError` от `int()`.
  `to_dict()` и `str(err)` дают точные тексты. Проверка: `T -k ParseMinQuantityTests.test_error`.
- **AC6 (R4).** HTTP: 14 неверных target из PLAN.md → 400, `application/json`, `Content-Length` == длине
  тела, тело == точному JSON раздела 5. Соединение не разрывается. Проверка:
  `T -k CatalogHTTPTests.test_invalid_values_return_400_json`.
- **AC7 (R5).** `parse_min_quantity` → `None` для `""`, `&`, `=5`, `foo=1`, `min_qty=3`, `MIN_QUANTITY=3`.
  HTTP `?min_qty=3`, `?MIN_QUANTITY=4`, `?foo=bar` → полный каталог, `?foo=bar&min_quantity=4` и
  `?min_quantity=4&foo=` → `[2]`. Проверка:
  `T -k ParseMinQuantityTests.test_absent_returns_none -k CatalogHTTPTests.test_unknown_parameters_are_ignored`.
- **AC8 (R6).** `list_items()` равен исходному литералу. Существующие тесты свежести проходят.
  `/` и `/?min_quantity=abc` → 200 `text/html; charset=utf-8` с `<h1>Inventory canary</h1>`,
  `Status: Draft`, `>Refresh</button>`. `/health` и `/health?min_quantity=-1` → 200 `{"ok": true}`.
  `/missing`, `/api/items/`, `/api/items/?min_quantity=1` → 404. Защищённые файлы не изменены. Проверка:
  `T -k InventoryTests -k CatalogHTTPTests.test_other_routes_unchanged && git diff --exit-code 57923dcefab1b47115a9bab26b4a73b8e879f19b -- labels.json README.md .agent/project.json .github notes`.
- **AC9 (R7).** Есть классы `InventoryTests`, `FilterItemsTests`, `ParseMinQuantityTests`,
  `CatalogHTTPTests` и проба `test_parse_qs_semantics_probe`. Quick-проверка проходит. Полный набор
  проходит в Verify контроллера (проверка `canary-tests`). Проверка исполнителем:
  `scripts/agent-check --phase quick && python3 -m py_compile tests/test_api.py && T -k ParseMinQuantityTests.test_parse_qs_semantics_probe`.
  Проверка контроллером (только Verify): `python3 -m unittest discover -s tests -v`.

UAT не требуется: меняется только JSON API, поведение полностью покрыто автотестами, brief прямо
исключает UAT.

## 9. Ответы на ожидаемые возражения оппонента (область из TEAM.json)

- *Пустые значения* — `keep_blank_values=True` (D1), код `empty` для `min_quantity=` и голого имени (AC5, AC6).
- *Повторы* — проверяются до разбора значения, включая одинаковые значения и закодированное имя (D5, AC5, AC6).
- *Границы N* — `>=` включает границу (AC2, AC3). 0 и 2^63−1 допустимы, 2^63 → `too_large` (AC4, AC5).
- *Числовая точность* — без `float`, без округления, `3.0` → `not_integer`. Длинные строки не доходят
  до `int()` (D4), а Unicode-цифры, пробелы, `+`, `_`, `\n` отвергаются (D3).
- *Регрессии* — байтовое равенство без фильтра (AC1), неизменность данных, UI и маршрутов (AC8).
  Политика проверок не меняется (D11).
- *Падение сервера* — исключение в `do_GET` рвёт соединение (раздел 2, п. 4). Все пути разбора
  возвращают 400 (D6, AC6).

## 10. Сверка документации

- Python `urllib.parse`, официальная документация https://docs.python.org/3/library/urllib.parse.html,
  версия страницы 3.15.2, прочитана 2026-11-08. Сигнатура
  `parse_qs(qs, keep_blank_values=False, strict_parsing=False, encoding='utf-8', errors='replace', max_num_fields=None, separator='&')`.
  3.10: разделитель только `&` (до 3.10 — ещё и `;`). 3.14: deprecated передача «ложных» объектов,
  кроме пустой строки (мы всегда передаём `str`, допустимо). `urlsplit`: 3.12 — отбрасывание
  ведущих C0/пробелов, 3.15 — новый параметр `missing_as_none` (по умолчанию поведение прежнее, не используем).
- Ограничение длины строки при `int()` (https://docs.python.org/3/library/stdtypes.html#int-max-str-digits):
  по умолчанию 4300 цифр, `ValueError` при превышении. Подтверждено локально:
  `sys.int_info.default_max_str_digits=4300`. Текст раздела получен в пересказе, не дословно.
- `http.server`, https://docs.python.org/3/library/http.server.html, версия 3.15.2 (страница обновлена
  и прочитана 2026-11-08). `ThreadingHTTPServer(server_address, RequestHandlerClass)` — с 3.7.
  `BaseHTTPRequestHandler.path` «includes the query». У `send_response`, `send_header`,
  `end_headers`, `send_error` и `log_message` нет изменений в 3.10–3.15. Deprecated/Removed на
  странице нет. Предупреждения: модуль «not recommended for production» (у нас синтетический тестовый
  сервер). `send_header` не очищает CRLF — в заголовки идут только константы и вычисленная длина,
  пользовательский ввод туда не попадает. `daemon_threads` на странице не описан, поэтому тесты не
  полагаются на него и явно вызывают `shutdown()`, `server_close()` и `join()`.
- Внешних пакетов нет. Воспроизводимая установка для Verify и CI — системный `python3` без установки
  зависимостей. Сборка CI (`ubuntu-latest`) не закреплена; это A1, его закрывает проба AC9.
- Пробы на CPython 3.12.3 (2026-11-08) подтвердили каждый пример раздела 2 и таблицу раздела 5:
  47 случаев эталонного алгоритма PLAN.md. HTTP-интеграция не запускалась — это работа исполнителя.
