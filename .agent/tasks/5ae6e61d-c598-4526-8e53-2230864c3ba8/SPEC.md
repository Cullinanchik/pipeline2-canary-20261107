# Canary 01 · Тривиальная замена статуса — ТЗ (перепланирование после конфликта слияния, ред. 2)

Задача `5ae6e61d-c598-4526-8e53-2230864c3ba8`, run `ffb63a25-af77-41f6-8033-1465f8678161`,
generation 23, context_digest `3f0439d6f5eded93a2937def51a43b1062c8805b33c3456d703d9cd39e9eaad4`.
Роль: Architect / Spec. Документ заменяет SPEC.md generation 21 и критерии AC1/AC2 из TEAM.json.

## Источники

- BRIEF: `.agent/runtime/5ae6e61d-c598-4526-8e53-2230864c3ba8/context/52bedf6f19cf88ee6c871122ec0351d76b599d06aec3af5badae9d01caa1ed7e.json`.
  Цель: в `labels.json` заменить единственное значение badge `Draft` → `Ready`; «остальные значения и поведение не менять»; ручной UAT не нужен.
- Возражения оппонента этого запуска (F1 major, F2 minor): `.agent/runtime/5ae6e61d-c598-4526-8e53-2230864c3ba8/context/69a618f8c386e9b4fa7046f9cabbabb7e23839c6ff379894aace35dc1b8f0bc2.json`; разбор — `DEBATE.md`, `DEBATE_FINDINGS.json` в каталоге задачи.
- Прежние SPEC/PLAN (generation 21): `…/context/83fac2591535aac843b534ad96cb6765852b126e2baf92e34ce26f5b31cacc01.json`, `…/context/05971fbf5b5ff706688b8c0db9cf5a44083759ac908b4b74bcd854c5cce011e7.json`, PLAN.json `…/context/a11b108d8bf093695c7de2fffd07e5e340db73a9294aa05f67e18b65c06fe9b4.json`.
- Закреплённая контроллером база: `request.integration_base` = `57923dcefab1b47115a9bab26b4a73b8e879f19b` (`…/context/351ef2a9ccea598eb8121bb84ececb682907127a17b6464fdf5d06e2bdf94463.json`).
- Причина перепланирования: `request.route.reason` (source `amendment`): владелец отклонил результат из-за конфликта слияния с main.
- `request.owner_answers` = `null` (`…/context/05bb8111e828d918fe554caa6f6063bcf7cc10eba25c771b9ab37142c241e8fd.json`): ответов и согласований владельца в контракте нет.
- Урок `request.lessons`: «конфликт при слиянии не устранён автоматически: target branch advanced; rebase and fresh Verify required» (×2) — учтён в D1, D3, AC4.

## Установленные факты (проверено архитектором 2026-11-08 после `git fetch origin`, git 2.43.0, Python 3.12.3)

- F1. `origin/main` = `fdbf1e4203a8770c7148668e14de48a79b65dad5`; история: `2561257` → `57923dc` → `5f22a42` (заголовок «Canary 10 · Проверка кнопки владельцем (#3)», button `Refresh` → `Reload items`) → `fdbf1e4` (Canary 08 A, `notes/parallel-a.txt`).
- F2. `git merge-base HEAD origin/main` = `57923dc` = закреплённая база. Поэтому rebase на неё ничего не меняет — корневая причина неустранённого конфликта.
- F3. `git merge-tree --write-tree HEAD origin/main` → код 1, конфликт только в `labels.json`. Пересечение файлов ветки (`57923dc..HEAD`: `labels.json` и каталог этой задачи) и upstream (`57923dc..fdbf1e4`: `labels.json`, `notes/parallel-a.txt`, каталоги других задач) — только `labels.json`. Конфликт соседних строк: ветка меняет badge, upstream — button.
- F4. `fdbf1e4:labels.json` — blob `14ee0ebf25856d061866cdb79ec0f413f36741b9`, `{"badge": "Draft", "button": "Reload items"}` (отступ 2 пробела, LF); `Draft` встречается ровно один раз.
- F5. Точная замена `Draft` → `Ready` в F4: 51 байт, blob `89b9bb8f13167ce927f4bca8912a103a2941360f`, sha256 `352244d37c6fd4eb0798d0403c51aa7bdc35edad55151feacd861e52dba46a6a`. Текущий `HEAD:labels.json` = `aa4dbcec…` (`Ready`/`Refresh`).
- F6. `app.py` читает `labels.json` при каждом запросе `/` и выводит `Status: <badge>` и кнопку `<button>` через `html.escape`; код менять не нужно.
- F7. Проверки проекта реальные: quick = `python3 -m py_compile app.py api.py`; full = `python3 -m unittest discover -s tests -v`. Внешних библиотек и API нет — проверка документации не требуется.

## Требования

- R1. В итоговом `labels.json` badge = `Ready`; файл получен одной точной заменой `Draft` → `Ready` в версии из базы интеграции B.
- R2. Выбранная база B и все upstream-изменения main до B (включая button = `Reload items` из `5f22a42` и `notes/parallel-a.txt` из `fdbf1e4`) содержатся в HEAD: B — предок HEAD.
- R3. Ветка `feature/canary-01-0k1` линейно перебазирована на B (нет merge-коммитов в `B..HEAD`) и отдельно от этого сливается с текущим `origin/main` без конфликтов.
- R4. Относительно B меняются только `labels.json` (строка badge) и документы в `.agent/tasks/5ae6e61d-c598-4526-8e53-2230864c3ba8/`; код, тесты, `notes/`, `.agent/project.json` и прочие файлы совпадают с B.
- R5. Проверки проекта проходят: quick — у исполнителя, полный набор — только контроллер на этапе Verify.

## Ограничения

- C1. Работа только в этом worktree и ветке. Агенты не делают push, merge, approve, step_complete и перемещение задач; публикацию (включая push переписанной ветки) выполняет контроллер.
- C2. Целью rebase никогда не служит «живой» `origin/main`: только B по правилу D1.
- C3. Полный набор тестов агенты не запускают; исполнитель запускает только `scripts/agent-check --phase quick` и команды AC.
- C4. `.agent/project.json`, зависимости и CI не меняются (смены политики проверок нет).
- C5. Конфликт разрешается только по D4; ручная правка маркеров и `-X ours/theirs` запрещены.
- C6. `TEAM.json` (артефакт Triage) не редактируется; действуют критерии этого SPEC и PLAN.json (D7).
- C7. Для AC4 нужен git ≥ 2.38 (`merge-tree --write-tree`); в worktree git 2.43.0.

## Решения

- D1. База интеграции B — чистая функция двух входов: константы P = `fdbf1e4203a8770c7148668e14de48a79b65dad5` (текущий `origin/main`, F1) и поля `integration_base` (I) из текущего `.agent/runtime/5ae6e61d-c598-4526-8e53-2230864c3ba8/request.json`:
  - I пуст или предок P (в т. ч. `57923dc`, а также I = P) → B = P;
  - I — потомок P (контроллер закрепил более новый main) → B = полный SHA I, при условии `B:labels.json` = blob `14ee0ebf…`; иначе остановка и `--amendment`;
  - иначе (ветвление, неизвестный коммит) → остановка и `--amendment`.
  Правило реализует фрагмент **BASE** (PLAN.md, раздел «Фрагмент BASE»), одинаковый в S1 и во всех командах AC2–AC4. Перезакрепить `request.integration_base` может только контроллер.
- D2. button = `Reload items`. Основание — правило BRIEF «остальные значения не менять», применённое к ветке, в которую идёт слияние: `5f22a42` уже слит в main, его откат был бы изменением чужого значения. Заголовок коммита — лишь описание; подтверждения приёмки кнопки владельцем в контракте нет (`owner_answers=null`), и для этого решения оно не используется. Прежний AC2 «button остаётся Refresh» фиксировал состояние базы `2561257` на момент Triage. Вариант «оставить Refresh» отвергнут.
- D3. Интеграция через `git rebase "$B"`, не merge-коммит: история линейная, B — предок HEAD (R2, R3). Push переписанной ветки делает контроллер (C1).
- D4. Разрешение конфликта: `labels.json` пересоздаётся из `B:labels.json` одной побайтовой заменой `Draft` → `Ready` с проверкой «ровно одно вхождение» (PLAN S2). Результат равен F5.
- D5. Новые тесты не добавляются: область BRIEF — одно значение в `labels.json`; тест с конкретными подписями связал бы проект с текстами других задач. Корректность доказывается точным blob (AC1), предком B (AC2), списком путей от B (AC3), линейностью от B и `merge-tree` с текущим main (AC4).
- D6. UAT не нужен (needs_uat=false): BRIEF прямо исключает ручной UAT; видимое изменение — одно слово статуса; подпись кнопки задача не меняет, а сохраняет из B; код отображения не меняется (F6); байты `labels.json` проверяются автоматически точным blob (AC1).
- D7. Прежние критерии заменены: TEAM AC1 → AC1; TEAM AC2 → AC2 + AC3; команда `git diff 2561257… -- labels.json` больше не используется.
- D8. Маршрут `standard`: правка механическая, но включает rebase на новую базу и разрешение конфликта по правилу.
- D9. Проверки привязаны к выбранной B, а не к `git merge-base HEAD origin/main` (ответ на возражение F1): AC2 требует B предком HEAD, AC3 сравнивает пути с B, AC4 проверяет линейность `B..HEAD` и отдельно — бесконфликтное слияние с текущим `origin/main`. Каждая роль (исполнитель, ревьюер) вычисляет B заново фрагментом BASE из своего `request.json`; исполнитель дополнительно записывает B в отчёт. Если контроллер к моменту Review перезакрепит базу на более новую, AC2/AC3 провалятся — это верный сигнал «устаревший результат → Fix с новой базой».

## Допущения (не блокируют работу)

- A1. Владелец хочет итоговые подписи в виде, в каком они сейчас в main, плюс только новый статус: `Ready` / `Reload items` (следует из BRIEF и D2). Это явно показано владельцу в отчёте для утверждения плана; отказ от плана с указанием `Refresh` вернёт задачу на перепланирование.
- A2. Остальные задачи canary, попадающие в main до слияния, не трогают `labels.json`. Если тронут — сработает D1 (остановка с `--amendment`) или AC4/цикл контроллера «конфликт → Fix с новой базой».
- A3. `git fetch origin` доступен исполнителю и ревьюеру. Если fetch недоступен, AC4 завершается ненулевым кодом и записывается как «не проверено», а не как пройденный.
- A4. Отображение страницы не проверяется запуском сервера: `app.py` не меняется (F6), подписи полностью определяются байтами `labels.json` (AC1).

## Критерии приёмки

`BASE` — фрагмент из PLAN.md (D1), вставляемый дословно в начало команды; он задаёт `$B` или завершается ненулевым кодом.

- AC1 (R1). `labels.json` в HEAD побайтно равен F5: `test "$(git rev-parse HEAD:labels.json)" = 89b9bb8f13167ce927f4bca8912a103a2941360f && python3 -I -c 'import json;assert json.load(open("labels.json"))=={"badge":"Ready","button":"Reload items"}'` — код 0.
- AC2 (R2). `BASE && git merge-base --is-ancestor "$B" HEAD && git merge-base --is-ancestor fdbf1e4203a8770c7148668e14de48a79b65dad5 HEAD && git merge-base --is-ancestor 5f22a42dd5e8cbf17890d7444c16ff87186cb09a HEAD` — код 0 (выбранная B, P и upstream-коммит кнопки — предки HEAD).
- AC3 (R4). `BASE && git merge-base --is-ancestor "$B" HEAD && test "$(git rev-parse "$B:labels.json")" = 14ee0ebf25856d061866cdb79ec0f413f36741b9 && test "$(git diff --name-only "$B" HEAD -- . ':(exclude).agent/tasks/5ae6e61d-c598-4526-8e53-2230864c3ba8')" = labels.json` — код 0.
- AC4 (R3). `BASE && git merge-base --is-ancestor "$B" HEAD && test -z "$(git rev-list --merges "$B..HEAD")" && git fetch origin && git merge-tree --write-tree HEAD origin/main >/dev/null` — код 0 (линейность от B и отдельно бесконфликтное слияние с текущим main).
- AC5 (R5). `scripts/agent-check --phase quick` — код 0 у исполнителя; полный набор `python3 -m unittest discover -s tests -v` — ok в Verify контроллера.

## Ответ на возражения оппонента (generation 22)

1. F1 [major] «Проверять выбранную базу B» — принято полностью (D9). Контрпример (I = N — потомок P, T построен только на P): AC2 теперь проваливается на `git merge-base --is-ancestor "$B" HEAD` (N не предок T); AC3 сравнивает с B = N и видит отсутствующий upstream-файл; AC4 проверяет линейность от B, а слияние с `origin/main` — отдельной командой. `git merge-base HEAD origin/main` из критериев удалён. Неверное утверждение в рисках («неверная база ловится AC2/AC3») заменено точным.
2. F2 [minor] «Убрать неподтверждённую приёмку кнопки» — принято: из `uat_reason`, D2, D6 и отчёта владельцу удалено утверждение о проверке кнопки владельцем; needs_uat=false обоснован BRIEF, сохранением upstream-подписи из B и автоматической проверкой байтов (D6).

## Ответ на поправку исполнителя (сохраняется из generation 21)

1. «Перезакрепить integration_base на fdbf1e4» — принято как D1 (само поле меняет только контроллер).
2. «Заменить AC2» — принято: AC1 (точные байты с `Reload items`), AC2 (предки), AC3 (только `labels.json` от B).
3. «Замена Draft→Ready в файле из текущего main» — принято как D4, результат F5.
4. Альтернатива «оставить Refresh» — отвергнута (D2).

## Вне области

Код (`app.py`, `api.py`), тесты, CI, `.agent/project.json`, `notes/`, дизайн и новые зависимости.
