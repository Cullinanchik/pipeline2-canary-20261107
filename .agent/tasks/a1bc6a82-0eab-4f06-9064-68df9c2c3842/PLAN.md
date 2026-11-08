# Canary 02 · Фильтрация синтетического каталога — план реализации

Задача `a1bc6a82-0eab-4f06-9064-68df9c2c3842` · run `73a73295-acf1-4a30-b1c7-281ab1aacfa4` · generation `4` ·
context_digest `a5d0b65cc3d3e2319721c1052bb6bb5450382f5c8653d3f8e3d3eac499412df9`. Требования, решения и критерии — в
SPEC.md (R1–R8, D1–D13, C1–C6, A1–A5, AC1–AC10). Машиночитаемая версия — PLAN.json.
Редакция 2: возражение оппонента F1 закрыто — журнал доступа без query (S2) и его тесты (S3), см. SPEC.md §9.

Правила для исполнителя:
- выполнять шаги по порядку и буквально, без альтернатив;
- менять только `api.py`, `app.py` и `tests/test_api.py`;
- не запускать полный набор (`python3 -m unittest discover -s tests -v`): это делает контроллер в Verify;
- разрешены только `scripts/agent-check --phase quick`, `python3 -m py_compile <файл>` и именованные
  тесты `T -k ...`, где `T` = `python3 -m unittest discover -s tests -p test_api.py`.

Политика проверок не меняется: `.agent/project.json` и `.github/` не трогать (`project_policy_change` не
нужен, D11). Ассетов нет.

## S1. `api.py` — чистые функции (AC2, AC4, AC5, AC7, AC8)

Файлы: `api.py`.

Изменение: строки 2–3 (`def list_items` и `return [...]`) остаются байт в байт. Docstring остаётся
первой строкой. Итоговый файл имеет ровно такой вид:

```python
"""Pure functions for the synthetic inventory application."""
import re
from urllib.parse import parse_qs

MIN_QUANTITY_PARAM = "min_quantity"
MAX_MIN_QUANTITY = 9223372036854775807  # 2**63 - 1
MIN_QUANTITY_ERRORS = {
    "duplicate": "min_quantity must be specified at most once",
    "empty": "min_quantity must not be empty",
    "too_large": "min_quantity must not exceed 9223372036854775807",
    "negative": "min_quantity must not be negative",
    "not_integer": "min_quantity must be a whole number",
    "invalid": "min_quantity must be a non-negative integer written with digits 0-9",
}
_DIGITS = re.compile(r"[0-9]+")
_NEGATIVE = re.compile(r"-0*[1-9][0-9]*")
_FRACTION = re.compile(r"[+-]?(?:[0-9]+\.[0-9]*|\.[0-9]+)")


class MinQuantityError(ValueError):
    """Invalid min_quantity query parameter; the HTTP layer answers 400."""

    def __init__(self, code):
        message = MIN_QUANTITY_ERRORS[code]
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self):
        return {"error": {"code": self.code, "parameter": MIN_QUANTITY_PARAM, "message": self.message}}


def list_items():
    return [{"id": 1, "name": "Notebook", "quantity": 3}, {"id": 2, "name": "Pencil", "quantity": 5}]


def parse_min_quantity(query):
    """Return None when min_quantity is absent, else its int value; raise MinQuantityError."""
    values = parse_qs(query, keep_blank_values=True).get(MIN_QUANTITY_PARAM)
    if values is None:
        return None
    if len(values) > 1:
        raise MinQuantityError("duplicate")
    raw = values[0]
    if raw == "":
        raise MinQuantityError("empty")
    if _DIGITS.fullmatch(raw):
        digits = raw.lstrip("0") or "0"
        if len(digits) > 19 or int(digits) > MAX_MIN_QUANTITY:
            raise MinQuantityError("too_large")
        return int(digits)
    if _NEGATIVE.fullmatch(raw):
        raise MinQuantityError("negative")
    if _FRACTION.fullmatch(raw):
        raise MinQuantityError("not_integer")
    raise MinQuantityError("invalid")


def filter_items(items, min_quantity):
    """Return a new list with items whose quantity >= min_quantity; input is not modified."""
    return [item for item in items if item["quantity"] >= min_quantity]
```

Подход: D1–D6. Нельзя использовать `int(raw)` без `_DIGITS.fullmatch`, а также `isdigit`, `\d`,
`re.match`, `strip` и `float`. Нельзя добавлять аннотации типов (C3). Порядок проверок — строго как выше (D5).

Проверка: `python3 -m py_compile api.py`.

## S2. `app.py` — HTTP-ветка, статус 400 и журнал без query (AC1, AC3, AC6, AC7, AC8, AC10)

Файлы: `app.py`. Зависит от S1.

Изменение: итоговый файл имеет ровно такой вид. Строки, которых нет в списке ниже, остаются байт в
байт как на base: ветки `/health`, `/`, `else: self.send_error(404); return`, отправка `Content-Type`
и `Content-Length`, блок `if __name__ == "__main__":`.

```python
"""Synthetic, read-only test server; no credentials or external data."""
import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from api import MinQuantityError, filter_items, list_items, parse_min_quantity

_QUERY_OR_FRAGMENT = re.compile(r"[?#]")


def redact_request_line(requestline):
    """Return the request line cut at the first '?' or '#', so access logs never contain query values."""
    match = _QUERY_OR_FRAGMENT.search(requestline)
    if match is None:
        return requestline
    return requestline[:match.start()] + " [query redacted]"


class Handler(BaseHTTPRequestHandler):
    def log_request(self, code="-", size="-"):
        if isinstance(code, HTTPStatus):
            code = code.value
        self.log_message('"%s" %s %s', redact_request_line(self.requestline), str(code), str(size))

    def do_GET(self):
        parts = urlsplit(self.path)
        path = parts.path
        status = 200
        if path == "/health":
            body, content = b'{"ok": true}', "application/json"
        elif path == "/api/items":
            content = "application/json"
            try:
                min_quantity = parse_min_quantity(parts.query)
            except MinQuantityError as error:
                status, body = 400, json.dumps(error.to_dict()).encode()
            else:
                items = list_items()
                if min_quantity is not None:
                    items = filter_items(items, min_quantity)
                body = json.dumps(items).encode()
        elif path == "/":
            labels = json.loads(Path(__file__).with_name("labels.json").read_text())
            body = ("<!doctype html><html lang='en'><meta charset='utf-8'><title>Synthetic canary</title>"
                    "<style>body{font:20px system-ui;max-width:720px;margin:60px auto;padding:20px}button{padding:12px}</style>"
                    "<h1>Inventory canary</h1><p>This is synthetic test data.</p><p>Status: " + html.escape(labels["badge"]) +
                    "</p><button type='button'>" + html.escape(labels["button"]) + "</button></html>").encode()
            content = "text/html; charset=utf-8"
        else:
            self.send_error(404); return
        self.send_response(status)
        self.send_header("Content-Type", content)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18390)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
```

Отличия от base (больше ничего не менять):
1. Импорты `from http import HTTPStatus` (после `import argparse`) и `import re` (после
   `from pathlib import Path`). `from api import list_items` →
   `from api import MinQuantityError, filter_items, list_items, parse_min_quantity`.
2. Константа `_QUERY_OR_FRAGMENT` и функция `redact_request_line` перед классом (D13, R8).
3. Метод `Handler.log_request` — копия стандартного, но с `redact_request_line(self.requestline)`
   (D13). `log_message` и `log_error` не переопределять.
4. Начало `do_GET`: `parts = urlsplit(self.path)`, `path = parts.path`, `status = 200`.
5. Ветка `/api/items` — разбор, 400 или фильтр (D7). Ловить только `MinQuantityError` (D6).
6. `self.send_response(200)` → `self.send_response(status)`.

Подход: D7, D13. Без параметра тело — те же `json.dumps(list_items()).encode()` (AC1, байтовое
равенство). Сырое значение не попадает ни в тело, ни в журнал (C5): тело 400 — константы раздела 5
SPEC.md, `log_error` при 404 — `code 404, message Not Found`, журнал доступа обрезан.

Проверка: `scripts/agent-check --phase quick`.

## S3. `tests/test_api.py` — тесты (AC1–AC10)

Файлы: `tests/test_api.py`. Зависит от S1 и S2.

Изменение: существующий класс `InventoryTests` и два его теста оставить без изменений и добавить в него
третий тест. Добавить пять новых классов. Импорты в начале файла:

```python
import contextlib
import copy
import http.client
import io
import json
import threading
import unittest
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs

from api import MAX_MIN_QUANTITY, MinQuantityError, filter_items, list_items, parse_min_quantity
from app import Handler, redact_request_line

CATALOG = [{"id": 1, "name": "Notebook", "quantity": 3}, {"id": 2, "name": "Pencil", "quantity": 5}]
MESSAGES = {
    "duplicate": "min_quantity must be specified at most once",
    "empty": "min_quantity must not be empty",
    "too_large": "min_quantity must not exceed 9223372036854775807",
    "negative": "min_quantity must not be negative",
    "not_integer": "min_quantity must be a whole number",
    "invalid": "min_quantity must be a non-negative integer written with digits 0-9",
}
```

`MESSAGES` и `CATALOG` — независимые литералы контракта. Не импортировать `MIN_QUANTITY_ERRORS` из `api`.
Ещё одна константа модуля: `PROBE = "synthetic_probe"`.

### `InventoryTests` (AC8)
- `test_items_have_unique_ids`, `test_items_are_fresh_values` — без изменений;
- `test_catalog_data_unchanged`: `self.assertEqual(list_items(), CATALOG)`.

### `FilterItemsTests` (AC2)
`SAMPLE = [{"id": 1, "quantity": 0}, {"id": 2, "quantity": 2}, {"id": 3, "quantity": 3}, {"id": 4, "quantity": 3}, {"id": 5, "quantity": 10}]`
- `test_boundary_is_inclusive_and_order_preserved`: id результата `filter_items(SAMPLE, 3)` == `[3, 4, 5]`;
- `test_zero_returns_all`: при пороге 0 id == `[1, 2, 3, 4, 5]`;
- `test_threshold_above_maximum_returns_empty`: при пороге `11` и `MAX_MIN_QUANTITY` результат `[]`;
- `test_empty_input_returns_empty`: `filter_items([], 0) == []`;
- `test_input_not_mutated_and_result_is_new_list`: `before = copy.deepcopy(SAMPLE)`,
  `result = filter_items(SAMPLE, 0)`; проверить `result is not SAMPLE`; после `result.append({})` —
  `SAMPLE == before`;
- `test_filtered_catalog_values_are_fresh`: `first = filter_items(list_items(), 4)`,
  `first[0]["quantity"] = -1`; затем `filter_items(list_items(), 4) == [CATALOG[1]]`.

### `ParseMinQuantityTests` (AC4, AC5, AC7, AC9)
- `test_absent_returns_none`: для `""`, `"&"`, `"=5"`, `"foo=1"`, `"min_qty=3"`, `"MIN_QUANTITY=3"` →
  `assertIsNone`.
- `test_valid_values`: через `subTest` по таблице — `"min_quantity=0"`→0, `"min_quantity=00"`→0,
  `"min_quantity=3"`→3, `"min_quantity=007"`→7, `"min_quantity=9223372036854775807"`→`MAX_MIN_QUANTITY`,
  `"min_quantity=" + "0" * 5000 + "1"`→1, `"min_quantity=4&foo=bar"`→4, `"foo=&min_quantity=4"`→4,
  `"min%5Fquantity=4"`→4. Проверять и значение, и `type(result) is int`.
- `test_error_codes`: для каждого из 32 случаев — `with self.assertRaises(MinQuantityError) as ctx`,
  затем `ctx.exception.code == code`:
  - `empty`: `"min_quantity="`, `"min_quantity"`;
  - `too_large`: `"min_quantity=9223372036854775808"`, `"min_quantity=99999999999999999999"`,
    `"min_quantity=1" + "0" * 5000`;
  - `negative`: `"min_quantity=-1"`, `"min_quantity=-05"`;
  - `not_integer`: `"min_quantity=2.5"`, `"min_quantity=3.0"`, `"min_quantity=.5"`, `"min_quantity=5."`,
    `"min_quantity=-2.5"`, `"min_quantity=%2B2.5"`;
  - `invalid`: `"min_quantity=-0"`, `"min_quantity=--1"`, `"min_quantity=abc"`, `"min_quantity=%2B1"`,
    `"min_quantity=+1"`, `"min_quantity=1e3"`, `"min_quantity=%D9%A1"`, `"min_quantity=%C2%B2"`,
    `"min_quantity=1%0A"`, `"min_quantity=1_000"`, `"min_quantity=0x10"`, `"min_quantity=%FF"`,
    `"min_quantity=1;min_quantity=2"`, `"min_quantity=-"`, `"min_quantity=."`, `"min_quantity=%20"`;
  - `duplicate`: `"min_quantity=3&min_quantity=3"`, `"min_quantity=3&min%5Fquantity=4"`,
    `"min_quantity=3&min_quantity="`.
- `test_error_messages_and_payload`: для каждого `code` из `MESSAGES` — `err = MinQuantityError(code)`;
  проверить `isinstance(err, ValueError)`, `str(err) == MESSAGES[code]`, `err.message == MESSAGES[code]` и
  `err.to_dict() == {"error": {"code": code, "parameter": "min_quantity", "message": MESSAGES[code]}}`.
- `test_parse_qs_semantics_probe` (проба совместимости, A1) — с `keep_blank_values=True` строго равны:
  `"min_quantity="`→`{"min_quantity": [""]}`, `"min_quantity"`→`{"min_quantity": [""]}`,
  `"min_quantity=+1"`→`{"min_quantity": [" 1"]}`,
  `"min_quantity=1;min_quantity=2"`→`{"min_quantity": ["1;min_quantity=2"]}`,
  `"min_quantity=3&min%5Fquantity=4"`→`{"min_quantity": ["3", "4"]}`.

### `CatalogHTTPTests` (AC1, AC3, AC6, AC7, AC8)
Модульный класс `QuietHandler(Handler)` с `def log_message(self, format, *args): pass` (только для
этого класса, журнал здесь не проверяется). В `setUpClass`:
`cls.server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)`,
`cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)`, `cls.thread.start()`.
В `tearDownClass`: `cls.server.shutdown()`, `cls.server.server_close()`, `cls.thread.join(timeout=5)`.
Помощник `get(self, target)` открывает новый
`http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)`, выполняет
`request("GET", target)` и в `finally` закрывает соединение. Возвращает
`(status, response.getheader("Content-Type"), response.getheader("Content-Length"), body_bytes)`.
- `test_no_filter_returns_full_catalog`: для `/api/items` и `/api/items?` — 200, `"application/json"`,
  `body == json.dumps(list_items()).encode()`, `json.loads(body) == CATALOG`.
- `test_filter_results`: через `subTest` — `0`→id `[1, 2]`, `3`→`[1, 2]`, `4`→`[2]`, `5`→`[2]`,
  `004`→`[2]`, `6`→`[]`, `9223372036854775807`→`[]`. Target `"/api/items?min_quantity=" + value`.
  Каждый ответ 200 `"application/json"`; объекты равны элементам `CATALOG` с этими id. Для `0` тело
  `== json.dumps(list_items()).encode()`.
- `test_invalid_values_return_400_json`: через `subTest` по 14 target → код:
  `?min_quantity=`→empty, `?min_quantity`→empty, `?min_quantity=-1`→negative,
  `?min_quantity=2.5`→not_integer, `?min_quantity=3.0`→not_integer, `?min_quantity=abc`→invalid,
  `?min_quantity=%2B1`→invalid, `?min_quantity=+1`→invalid, `?min_quantity=%D9%A1`→invalid,
  `?min_quantity=1%0A`→invalid, `?min_quantity=9223372036854775808`→too_large,
  `?min_quantity=3&min_quantity=3`→duplicate, `?min_quantity=3&min%5Fquantity=4`→duplicate,
  `?min_quantity=1;min_quantity=2`→invalid. Каждый target имеет префикс `/api/items`. Проверить:
  статус 400, `"application/json"`, `int(Content-Length) == len(body)`,
  `json.loads(body) == {"error": {"code": code, "parameter": "min_quantity", "message": MESSAGES[code]}}`.
- `test_unknown_parameters_are_ignored`: `/api/items?min_qty=3`, `/api/items?MIN_QUANTITY=4`,
  `/api/items?foo=bar` → 200 и `json.loads(body) == CATALOG`; `/api/items?foo=bar&min_quantity=4` и
  `/api/items?min_quantity=4&foo=` → `[CATALOG[1]]`.
- `test_other_routes_unchanged`: `/` и `/?min_quantity=abc` → 200, `"text/html; charset=utf-8"`, тело
  содержит `b"<h1>Inventory canary</h1>"`, `b"Status: Draft"`, `b">Refresh</button>"`, тела обоих
  ответов равны. `/health` и `/health?min_quantity=-1` → 200, `"application/json"`, тело `b'{"ok": true}'`.
  `/missing`, `/api/items/`, `/api/items/?min_quantity=1` → 404.

### `RedactRequestLineTests` (AC10)
- `test_redact_request_line`: через `subTest`, `redact_request_line(line) == expected` для 7 пар:
  `"GET /api/items?min_quantity=synthetic_probe HTTP/1.1"` → `"GET /api/items [query redacted]"`;
  `"GET /api/items HTTP/1.1"` → без изменений;
  `"GET /api/items#min_quantity=synthetic_probe HTTP/1.1"` → `"GET /api/items [query redacted]"`;
  `"GET /api/items?min_quantity=1 2 HTTP/1.1"` → `"GET /api/items [query redacted]"`;
  `"GET /?a#b HTTP/1.1"` → `"GET / [query redacted]"`;
  `"GET /api/items? HTTP/1.1"` → `"GET /api/items [query redacted]"`; `""` → `""`.
- `test_log_request_redacts_query`: `handler = object.__new__(Handler)` (без сокета; `__init__`
  сразу обслуживает соединение, поэтому не вызывается), `handler.requestline =
  "GET /api/items?min_quantity=" + PROBE + " HTTP/1.1"`, `handler.client_address = ("127.0.0.1", 0)`.
  Через `subTest` для пар `(HTTPStatus.BAD_REQUEST, "400")`, `(200, "200")`, `("-", "-")`:
  `captured = io.StringIO()`, `with contextlib.redirect_stderr(captured): handler.log_request(code)`;
  затем `'"GET /api/items [query redacted]" ' + text + " -"` входит в `captured.getvalue()`, а `PROBE` и
  `"min_quantity"` — нет.

### `RequestLogHTTPTests` (AC10)
Настоящий `Handler`, не `QuietHandler`. `setUpClass`/`tearDownClass` — как в `CatalogHTTPTests`, но с
`ThreadingHTTPServer(("127.0.0.1", 0), Handler)`. Помощник `get_logged(self, target)`: внутри
`with contextlib.redirect_stderr(captured)` (где `captured = io.StringIO()`) открыть
`HTTPConnection` с `timeout=5`, `request("GET", target)`, прочитать ответ, в `finally` закрыть соединение.
Вернуть `(status, body_bytes, captured.getvalue())`. Журнал пишется в `send_response` до отправки
ответа, поэтому к моменту чтения ответа он уже перехвачен (D10).
- `test_access_log_omits_query`: через `subTest` по 5 случаям `(target, status, path, secrets)`:
  - `"/api/items?min_quantity=" + PROBE`, 400, `/api/items`, `[PROBE]`;
  - `"/api/items?min_quantity=" + "x" * 5000`, 400, `/api/items`, `["x" * 64]`;
  - `"/api/items?min_quantity=" + "0" * 64 + "4" + "&note=" + PROBE`, 200, `/api/items`, `["0" * 64, PROBE]`;
  - `"/health?min_quantity=" + PROBE`, 200, `/health`, `[PROBE]`;
  - `"/missing?min_quantity=" + PROBE`, 404, `/missing`, `[PROBE]`.

  Для каждого: статус равен ожидаемому; `'"GET ' + path + ' [query redacted]" ' + str(status) + " -"`
  входит в журнал; `"min_quantity"` не входит в журнал; каждый `secret` не входит ни в журнал, ни в
  тело (`secret.encode() not in body`).
- `test_access_log_without_query_unchanged`: `/api/items` → 200, журнал содержит
  `'"GET /api/items HTTP/1.1" 200 -'` и не содержит `"[query redacted]"`.

Подход: D10, D13, без сетевых портов кроме эфемерного на 127.0.0.1 и без внешних библиотек. Имена
классов выбраны так, что `-k HTTP` выбирает только `CatalogHTTPTests` и `RequestLogHTTPTests`, а
`-k InventoryTests` — только `InventoryTests`.

Проверка (только именованные тесты; по отдельности, а не единым полным прогоном):
`python3 -m py_compile tests/test_api.py`,
`T -k FilterItemsTests`, `T -k ParseMinQuantityTests`, `T -k RedactRequestLineTests`, `T -k HTTP`,
`T -k InventoryTests`.

## S4. Коммит, quick-проверка и передача (AC8, AC9)

Файлы: без новых правок; коммит `api.py`, `app.py`, `tests/test_api.py`. Зависит от S3.

Изменение:
1. `git add api.py app.py tests/test_api.py` и коммит с заголовком
   `Canary 02 · Фильтр min_quantity для каталога`.
2. После коммита выполнить `scripts/agent-check --phase quick`.
3. Убедиться, что защищённые файлы не изменены:
   `git diff --exit-code 57923dcefab1b47115a9bab26b4a73b8e879f19b -- labels.json README.md .agent/project.json .github notes`.
4. Сформировать передачу `scripts/pipeline-report --task a1bc6a82-0eab-4f06-9064-68df9c2c3842` с флагами,
   которые требует request.role исполнителя.

Подход: C4, C6 — без push, merge и полного набора. Полный набор `canary-tests` запускает контроллер в Verify.

Проверка: `scripts/agent-check --phase quick && git status --porcelain` — пустой вывод для файлов кода.

## Риски и откат

- Неверная классификация экзотических строк. Закрыто таблицей из 32 случаев (AC5) и эталонным
  алгоритмом, сверенным на 47 случаях.
- Отличие `parse_qs` в будущих версиях Python (A1). Закрыто пробой `test_parse_qs_semantics_probe`.
- Зависание HTTP-тестов. Таймаут 5 с у клиента, эфемерный порт, явные `shutdown`, `server_close` и `join`.
- Регрессия каталога. Закрыто байтовым равенством (AC1) и литералом данных (AC8).
- Утечка query в журнал (F1). Закрыто `redact_request_line` и `Handler.log_request` (D13) и тестами
  настоящего `Handler` с перехватом stderr (AC10). Остаток — неверная строка запроса HTTP (A5).
- Формат журнала доступа меняется для запросов с query на всех маршрутах. Это осознанно (C5), без
  query формат прежний (AC10). Внешних разборщиков журнала у синтетического сервера нет.
- Откат — `git revert` коммита S4 (D12). Миграций и данных нет.

## Сверка API

Python `urllib.parse` и `http.server`: официальная документация 3.15.2 прочитана 2026-11-08 (журнал —
повторно в редакции 2). Детали, версии, исходник `log_request` 3.12.3 и ограничения — SPEC.md, раздел 10. Внешних пакетов и установки зависимостей нет: Verify и CI
используют системный `python3` ≥ 3.10 (C3).
