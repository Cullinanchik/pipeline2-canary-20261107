# Canary 01 · Тривиальная замена статуса — ТЗ (перепланирование после конфликта слияния)

Задача `5ae6e61d-c598-4526-8e53-2230864c3ba8`, run `00fbd42c-fd39-415a-ae49-9a9a19976a4f`,
generation 21, context_digest `caf29abedb18ccf78dc15a95f0b4cb918cbb581f1e589776bc0a18f67cfe46cb`.
Роль: Architect / Spec. Этот документ заменяет прежние SPEC.md/PLAN.md и критерии AC1/AC2 из TEAM.json.

## Источники

- BRIEF: `.agent/runtime/5ae6e61d-c598-4526-8e53-2230864c3ba8/context/52bedf6f19cf88ee6c871122ec0351d76b599d06aec3af5badae9d01caa1ed7e.json`.
  Цель: в `labels.json` заменить единственное значение badge `Draft` → `Ready`; «остальные значения и поведение не менять»; ручной UAT не нужен.
- Поправка исполнителя (обратная связь этого запуска): `.agent/runtime/5ae6e61d-c598-4526-8e53-2230864c3ba8/context/9b622949b02119bda36e2f3afd46da29a03bf685954a275d6dc51bd4ae30bc70.json`.
- Отказ владельца «Конфликт мержа с мейн веткой»: `.agent/runtime/5ae6e61d-c598-4526-8e53-2230864c3ba8/context/8c1cf264213e827b161b9fba99ffcafd0315573b84e51cd1ef1ede6cd5c6d2ae.json`.
- Закреплённая контроллером база (устаревшая): `.agent/runtime/5ae6e61d-c598-4526-8e53-2230864c3ba8/context/351ef2a9ccea598eb8121bb84ececb682907127a17b6464fdf5d06e2bdf94463.json` = `57923dcefab1b47115a9bab26b4a73b8e879f19b`.
- Последний Verify (HEAD `0afc426`, ok): `.agent/runtime/5ae6e61d-c598-4526-8e53-2230864c3ba8/context/c6273b83d2f0c09e40c38cf6841f0a0797c535acceb9b5f0b47eea1c3de3d0e6.json`.

## Установленные факты (проверено архитектором 2026-11-08, git 2.43.0, Python 3.12.3)

- F1. `origin/main` = `fdbf1e4203a8770c7148668e14de48a79b65dad5`; история: `2561257` → `57923dc` → `5f22a42` (Canary 10, button `Refresh` → `Reload items`) → `fdbf1e4` (Canary 08 A, `notes/parallel-a.txt`).
- F2. `git merge-base HEAD origin/main` = `57923dc`. Поэтому rebase на закреплённую базу `57923dc` ничего не меняет — это корневая причина неустранённого конфликта.
- F3. `git merge-tree --write-tree HEAD origin/main` → `CONFLICT (content): Merge conflict in labels.json`, других конфликтов нет. Пересечение файлов, изменённых веткой (`57923dc..HEAD`) и upstream (`57923dc..fdbf1e4`), — только `labels.json`. Конфликт «соседних строк»: ветка меняет строку 2 (badge), upstream — строку 3 (button); смысловых противоречий нет.
- F4. `fdbf1e4:labels.json` (blob `14ee0ebf25856d061866cdb79ec0f413f36741b9`) = `{"badge": "Draft", "button": "Reload items"}` с переводами строк и отступом 2 пробела; `Draft` встречается ровно один раз.
- F5. Точная замена `Draft` → `Ready` в F4 даёт байты `{\n  "badge": "Ready",\n  "button": "Reload items"\n}\n` (51 байт), git blob `89b9bb8f13167ce927f4bca8912a103a2941360f`, sha256 `352244d37c6fd4eb0798d0403c51aa7bdc35edad55151feacd861e52dba46a6a`.
- F6. `app.py` читает `labels.json` при каждом запросе `/` и выводит `Status: <badge>` и кнопку `<button>` через `html.escape`; код менять не нужно.
- F7. Проверки проекта реальные, не заглушки: quick = `python3 -m py_compile app.py api.py`; full = `python3 -m unittest discover -s tests -v` (CI делает то же). Внешних библиотек и API нет.

## Требования

- R1. В итоговом `labels.json` значение badge равно `Ready`; получено одной точной заменой `Draft` → `Ready` в версии файла из базы интеграции B.
- R2. Все upstream-изменения main до B сохранены: button = `Reload items` (коммит `5f22a42`), `notes/parallel-a.txt` из `fdbf1e4` и прочие файлы main не откатываются.
- R3. Ветка `feature/canary-01-0k1` линейно перебазирована на B и сливается с текущим main без конфликтов.
- R4. Относительно B меняется только `labels.json` (одна строка badge) и документы задачи в `.agent/tasks/5ae6e61d-c598-4526-8e53-2230864c3ba8/`; исходный код, тесты, `notes/`, `.agent/project.json` и прочие файлы совпадают с B.
- R5. Проверки проекта проходят: quick — у исполнителя, полный набор — только контроллер на этапе Verify.

## Ограничения

- C1. Работа только в этом worktree и ветке. Агенты не делают push, merge, approve, step_complete и перемещение задач; публикацию (включая push переписанной ветки) выполняет контроллер.
- C2. Целью rebase никогда не служит «живой» `origin/main`: только P = `fdbf1e4203a8770c7148668e14de48a79b65dad5` или более новая база, закреплённая контроллером, по правилу D1.
- C3. Полный набор тестов агенты не запускают; исполнитель запускает только `scripts/agent-check --phase quick` и команды проверки AC.
- C4. `.agent/project.json`, зависимости и CI не меняются (смены политики проверок нет).
- C5. Конфликт разрешается только восстановлением файла по правилу D4; ручная правка маркеров конфликта и стратегии `-X ours/theirs` запрещены.
- C6. `TEAM.json` (артефакт Triage) не редактируется; действуют критерии этого SPEC и PLAN.json (D7).
- C7. Для AC4 нужен git ≥ 2.38 (`merge-tree --write-tree`); в worktree стоит git 2.43.0.

## Решения

- D1. База интеграции. Плановое закрепление P = `fdbf1e4` (текущий `origin/main`, F1) вместо устаревшего `57923dc` (F2). Перезакрепить `request.integration_base` архитектор не может — это делает контроллер, поэтому база выбирается детерминированно по `request.integration_base` (I) текущего запроса Work/Fix:
  - I пуст или является предком P (в т. ч. `57923dc`) → B = P;
  - I — потомок P (контроллер закрепил более новый main) → B = I, но только если `B:labels.json` по-прежнему blob `14ee0ebf…`; иначе остановка и `--amendment`;
  - иначе (ветвление истории, неизвестный коммит) → остановка и `--amendment`.
- D2. button = `Reload items`. Основание: BRIEF требует не менять остальные значения — относительно main, куда идёт слияние; `5f22a42` — слитое изменение «Проверка кнопки владельцем (#3)». Прежний AC2 «button остаётся Refresh» лишь фиксировал состояние базы `2561257` на момент Triage. Альтернатива «оставить Refresh» отвергнута: она откатывает upstream-изменение и противоречит BRIEF.
- D3. Интеграция через `git rebase "$B"`, а не merge-коммит: этого ждёт контроллер («выполни rebase на актуальную базу»), история остаётся линейной, B — предок HEAD. Push переписанной ветки делает контроллер (C1).
- D4. Разрешение конфликта: `labels.json` пересоздаётся из `B:labels.json` одной побайтовой заменой `Draft` → `Ready` с проверкой «ровно одно вхождение» (команда в PLAN S2). Результат по байтам равен F5.
- D5. Новые тесты не добавляются: BRIEF ограничивает задачу одним значением в `labels.json`; тест с конкретными подписями привязал бы проект к текстам других задач (button) и расширил бы область. Корректность проверяется точным сравнением blob (AC1), предками (AC2), списком изменённых путей (AC3) и `merge-tree` (AC4).
- D6. UAT не нужен (needs_uat=false): видимый результат — одно слово статуса; подпись кнопки уже проверена владельцем в Canary 10; BRIEF явно исключает ручной UAT.
- D7. Прежние критерии заменяются: TEAM AC1 → AC1; TEAM AC2 → AC2 + AC3; команда `git diff 2561257… -- labels.json` больше не используется.
- D8. Маршрут `standard`: правка текста механическая, но включает перебазирование на новую базу и разрешение конфликта по правилу; путь по одной лишь замене (fast path) здесь неприменим.

## Допущения (не блокируют работу)

- A1. Владелец хочет итоговые подписи в виде, в каком они сейчас в main, плюс только новый статус: `Ready` / `Reload items` (следует из BRIEF и D2). Это явно показано владельцу в отчёте для утверждения плана.
- A2. Остальные задачи canary, которые могут попасть в main до слияния, не трогают `labels.json`. Если тронут — срабатывает D1 (остановка с `--amendment`) или цикл контроллера «конфликт → Fix с новой базой».
- A3. После `git fetch origin` локальный `origin/main` является B или его потомком; на этом держатся проверки AC3/AC4 через `git merge-base HEAD origin/main`.
- A4. Отображение страницы не проверяется запуском сервера: `app.py` не меняется (F6), а подписи полностью определяются байтами `labels.json` (AC1).

## Критерии приёмки

- AC1 (R1). `labels.json` в HEAD побайтно равен F5: `test "$(git rev-parse HEAD:labels.json)" = 89b9bb8f13167ce927f4bca8912a103a2941360f && python3 -I -c 'import json;assert json.load(open("labels.json"))=={"badge":"Ready","button":"Reload items"}'` — код выхода 0.
- AC2 (R2). Upstream сохранён, база не устаревшая: `git merge-base --is-ancestor fdbf1e4203a8770c7148668e14de48a79b65dad5 HEAD && git merge-base --is-ancestor 5f22a42dd5e8cbf17890d7444c16ff87186cb09a HEAD` — код выхода 0.
- AC3 (R4). Вне каталога задачи от B отличается только `labels.json`, а B содержит upstream-версию файла: `B=$(git merge-base HEAD origin/main); test "$(git diff --name-only "$B" HEAD -- . ':(exclude).agent/tasks/5ae6e61d-c598-4526-8e53-2230864c3ba8')" = labels.json && test "$(git rev-parse "$B:labels.json")" = 14ee0ebf25856d061866cdb79ec0f413f36741b9` — код выхода 0.
- AC4 (R3). Слияние с main без конфликтов, история линейная: `git fetch origin && git merge-tree --write-tree HEAD origin/main >/dev/null && test -z "$(git rev-list --merges "$(git merge-base HEAD origin/main)"..HEAD)"` — код выхода 0.
- AC5 (R5). `scripts/agent-check --phase quick` — код выхода 0 у исполнителя; полный набор `python3 -m unittest discover -s tests -v` — ok в Verify контроллера.

## Ответ на поправку исполнителя

1. «Перезакрепить integration_base на fdbf1e4» — принято как D1: план закрепляет P = `fdbf1e4` и задаёт правило для любой будущей базы контроллера; само поле запроса меняет только контроллер.
2. «Заменить AC2» — принято: AC2 (предки), AC3 (только `labels.json` от B), AC1 (точные байты с `Reload items`).
3. «Замена Draft→Ready в файле из текущего main» — принято как D4, результат F5.
4. Альтернатива «оставить Refresh» — отвергнута (D2).

## Вне области

Код (`app.py`, `api.py`), тесты, CI, `.agent/project.json`, `notes/`, дизайн и новые зависимости.
