# Canary 02 · Фильтрация синтетического каталога — план реализации

Задача `a1bc6a82-0eab-4f06-9064-68df9c2c3842` · run `bf001757-2c27-4a3e-b64b-ca755fe89097` · generation `2` ·
context_digest `1194a1e049737c76d697b0371c05473f93f1fadc3d7bcdd243ad3f1ab00dba0b`. Требования, решения и критерии — в
SPEC.md (R1–R7, D1–D12, C1–C6, A1–A4, AC1–AC9). Машиночитаемая версия — PLAN.json.

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

## S2. `app.py` — HTTP-ветка и статус 400 (AC1, AC3, AC6, AC7, AC8)

Файлы: `app.py`. Зависит от S1.

Изменение — только три места, остальные строки не трогать:
1. Строка 8: `from api import list_items` →
   `from api import MinQuantityError, filter_items, list_items, parse_min_quantity`.
2. Начало `do_GET` (строка 12): заменить `path = urlsplit(self.path).path` на
   ```python
           parts = urlsplit(self.path)
           path = parts.path
           status = 200
   ```
3. Ветку `elif path == "/api/items":` (строки 15–16) заменить на
   ```python
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
   ```
4. Строка 26: `self.send_response(200)` → `self.send_response(status)`.

Ветки `/health`, `/`, `else: self.send_error(404)`, отправку `Content-Type` и `Content-Length` и блок
`if __name__ == "__main__":` не менять. Ловить только `MinQuantityError` (D6). Сырое значение не
логировать и не возвращать (C5).

Подход: D7. Без параметра тело — те же `json.dumps(list_items()).encode()` (AC1, байтовое равенство).

Проверка: `scripts/agent-check --phase quick`.

## S3. `tests/test_api.py` — тесты (AC1–AC9)

Файлы: `tests/test_api.py`. Зависит от S1 и S2.

Изменение: существующий класс `InventoryTests` и два его теста оставить без изменений и добавить в него
третий тест. Добавить три новых класса. Импорты в начале файла:

```python
import copy
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs

from api import MAX_MIN_QUANTITY, MinQuantityError, filter_items, list_items, parse_min_quantity
from app import Handler

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
Модульный класс `QuietHandler(Handler)` с `def log_message(self, format, *args): pass`. В `setUpClass`:
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

Подход: D10, без сетевых портов кроме эфемерного на 127.0.0.1 и без внешних библиотек. Имена классов
выбраны так, что `-k HTTP` выбирает только `CatalogHTTPTests`, а `-k InventoryTests` — только `InventoryTests`.

Проверка (только именованные тесты; по отдельности, а не единым полным прогоном):
`python3 -m py_compile tests/test_api.py`,
`T -k FilterItemsTests`, `T -k ParseMinQuantityTests`, `T -k HTTP`, `T -k InventoryTests`.

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
- Откат — `git revert` коммита S4 (D12). Миграций и данных нет.

## Сверка API

Python `urllib.parse` и `http.server`: официальная документация 3.15.2 прочитана 2026-11-08. Детали,
версии и ограничения — SPEC.md, раздел 10. Внешних пакетов и установки зависимостей нет: Verify и CI
используют системный `python3` ≥ 3.10 (C3).
