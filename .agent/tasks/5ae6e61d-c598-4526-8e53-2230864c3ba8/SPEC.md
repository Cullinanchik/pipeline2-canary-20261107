# Canary 01 · Тривиальная замена статуса — ТЗ (ред. 3: проверка целостности после смены контракта)

Задача `5ae6e61d-c598-4526-8e53-2230864c3ba8`, run `40e30778-9ab7-4b99-a45c-772a90f7c37a`,
generation 27, context_digest `5f0eee644d24b661f78a795d2715f0a5b9f0841a59eb5cfa036eb4f5608f9964`.
Роль: Architect / Spec. Документ заменяет ред. 2 (generation 23, коммит `2ede0ad`, спор generation 24 — `clean`).
Обратная связь запуска: «контракт изменён; архитектор проверит целостность перед новым спором и согласованием» — раздел «Проверка целостности».

## Источники

- BRIEF: `.agent/runtime/5ae6e61d-c598-4526-8e53-2230864c3ba8/context/52bedf6f19cf88ee6c871122ec0351d76b599d06aec3af5badae9d01caa1ed7e.json`.
  Цель: в `labels.json` заменить единственное значение badge `Draft` → `Ready`; «остальные значения и поведение не менять»; ручной UAT не нужен.
- Контракт: текущий `.agent/runtime/5ae6e61d-c598-4526-8e53-2230864c3ba8/request.json` — `team` (AC1–AC5, class `standard`), `route` (source `amendment`, builder `deepseek`), `integration_base` (`…/context/351ef2a9ccea598eb8121bb84ececb682907127a17b6464fdf5d06e2bdf94463.json`), `feedback` (`…/context/c37c89b13ba0952619a8cefdb7a2dd845d194e8b1b9450c289ea717acc0dd69e.json`).
- Ред. 2, прошедшая спор: SPEC `…/context/be99a187e150433679fb721734fbba0580eeafe2a10e161f988491e3fa727d91.json`, PLAN.md `…/context/6415c656f8cef4ac4c46ca087a11953ecf89f7e69f207eb87b5986ba41215abe.json`, PLAN.json `…/context/7452bddd278d722cdaeddc780656fce12c0de9606f3edffe55bbe698f37b6c08.json`; итог спора — `DEBATE.md`, `DEBATE_FINDINGS.json` (`[]`) в каталоге задачи (относятся к ред. 2).
- `request.owner_answers` = `null`, `request.checks` = `null`, `request.approved_spec` = `""` (`…/context/05bb8111e828d918fe554caa6f6063bcf7cc10eba25c771b9ab37142c241e8fd.json`): ответов, проверок и утверждений владельца в контракте нет.
- Уроки `request.lessons`: «конфликт при слиянии не устранён автоматически: target branch advanced; rebase and fresh Verify required» (×2), «конфликт при мерже» (отказ владельца) — учтены в D1, D10, AC4.

## Проверка целостности (generation 27, 2026-11-08, git 2.43.0, Python 3.12.3)

- I1. Критерии `request.team.criteria` AC1–AC5 побайтно совпадают с `expected` из PLAN.json ред. 2; `team.class` = `route.class` = `standard`. Смена контракта — это перенос критериев ред. 2 в `team`; противоречий с ред. 2 нет.
- I2. Устаревшие поля контракта: `request.team.verification` всё ещё содержит `git diff 2561257… -- labels.json`, а `request.team.reason` и файл `TEAM.json` — «button имеет значение Refresh». Они не используются (D7); правило проверки задают только AC1–AC6 ниже.
- I3. В начале сессии worktree был в незавершённом rebase на `fdbf1e4`: запущен 2026-11-08 01:53:50 UTC (reflog), остановлен на `0afc426` с конфликтом в `labels.json`, 4 коммита не применены; ветка `feature/canary-01-0k1` оставалась на `1ee827b`. Кто запустил rebase, в контракте не записано (A6).
- I4. Из-за I3 артефакты `request.context` SPEC.md/PLAN.md/DESIGN.md/design.json (`3f33b2…`, `abbd7c…`, `8b41b5…`, `ca6b71…`) — версии Triage, а PLAN.json, ROUTE.json, OWNER_SPEC.json в снимке отсутствуют. Ред. 2 в `1ee827b` побайтно равна объектам `be99a187…`, `6415c656…`, `7452bddd…` (проверено). Новый спор должен читать файлы этой ред. 3.
- I5. Архитектор выполнил `git rebase --abort` (раздел «Откат» плана ред. 2): ветка = `1ee827b`, дерево чистое. Конфликт не разрешался — это работа исполнителя.
- I6. `origin/main` ушёл дальше константы ред. 2 P = `fdbf1e4`: `3018963` (Canary 03, #6) и `513a91f` (Canary 09 B, #5). `labels.json` в них не менялся. `request.integration_base` по-прежнему `57923dc` (не перезакреплён).
- I7. Утверждений нет (`approved_spec` пуст): вердикт `clean` спора generation 24 относится к ред. 2 и на ред. 3 не переносится.

## Установленные факты (после `git fetch origin` 2026-11-08)

- F1. `origin/main` = `513a91f5e0a25adea3a44e74db6fb9b15b230f05`. История от закреплённой базы: `57923dc` → `5f22a42` («Canary 10 · Проверка кнопки владельцем (#3)», button `Refresh` → `Reload items`) → `fdbf1e4` (Canary 08 A, `notes/parallel-a.txt`) → `3018963` (Canary 03: `app.py`, `api.py`, `tests/test_api.py`, `tests/test_reservations_http.py`, `README.md`, `.gitignore`, свой каталог задачи) → `513a91f` (Canary 09 B: `notes/parallel-b.txt`, свой каталог). В `57923dc..513a91f` `labels.json` менял только `5f22a42`.
- F2. `git merge-base HEAD origin/main` = `57923dc` = `integration_base`; rebase на неё ничего не меняет — корневая причина конфликта, отклонённого владельцем.
- F3. `git merge-tree --write-tree HEAD origin/main` → код 1. Ветка (`57923dc..HEAD`) меняет только `labels.json` и каталог этой задачи; upstream каталог этой задачи не трогает. Последовательный прогон 7 коммитов ветки поверх `513a91f` на висячих объектах (merge-tree + commit-tree, без изменения веток и дерева): конфликт только у `0afc426` и только в `labels.json`; после D4 — blob F5, от `513a91f` вне каталога задачи отличается только `labels.json`, `merge-tree` с `origin/main` — код 0.
- F4. `513a91f:labels.json` — blob `14ee0ebf25856d061866cdb79ec0f413f36741b9` (тот же, что в `fdbf1e4` и `3018963`): `{"badge": "Draft", "button": "Reload items"}`, отступ 2 пробела, LF; `Draft` встречается ровно один раз.
- F5. Точная замена `Draft` → `Ready` в F4: 51 байт, blob `89b9bb8f13167ce927f4bca8912a103a2941360f`, sha256 `352244d37c6fd4eb0798d0403c51aa7bdc35edad55151feacd861e52dba46a6a`. Сейчас `HEAD:labels.json` = `aa4dbcec…` (`Ready`/`Refresh`).
- F6. `513a91f:app.py`, строки 121–126: на `GET /` читает `labels.json` при каждом запросе и выводит `Status: <badge>` и `<button>` через `html.escape`. Код менять не нужно.
- F7. `513a91f:tests/test_reservations_http.py`, строки 221–227, `HttpTestCase.test_ac11_root_page_and_health_unchanged`: `GET /` → 200, каждое значение из `labels.json` присутствует в теле страницы, `/health` → `{"ok": true}`. В `fdbf1e4` этого теста нет.
- F8. Проверки проекта реальные и в `513a91f` не изменены: quick = `python3 -m py_compile app.py api.py`; full = `python3 -m unittest discover -s tests -v`. Внешних библиотек и API нет — проверка документации не требуется.

## Требования

- R1. В итоговом `labels.json` badge = `Ready`; файл получен одной точной заменой `Draft` → `Ready` в версии из базы интеграции B.
- R2. Выбранная база B и все upstream-изменения main до B (button `Reload items` из `5f22a42`, `notes/parallel-a.txt`, резервирование из `3018963`, `notes/parallel-b.txt`) содержатся в HEAD: B — предок HEAD.
- R3. Ветка `feature/canary-01-0k1` линейно перебазирована на B (нет merge-коммитов в `B..HEAD`) и отдельно сливается с текущим `origin/main` без конфликтов.
- R4. Относительно B меняются только `labels.json` (строка badge) и документы в `.agent/tasks/5ae6e61d-c598-4526-8e53-2230864c3ba8/`; код, тесты, `notes/`, `.agent/project.json` и прочие файлы совпадают с B.
- R5. Проверки проекта проходят: quick — у исполнителя, полный набор — только контроллер на этапе Verify.
- R6. Страница `/` на результате показывает новые подписи `labels.json` (`Status: Ready`, кнопка `Reload items`) — проверяется именованным тестом F7.

## Ограничения

- C1. Работа только в этом worktree и ветке. Агенты не делают push, merge, approve, step_complete и перемещение задач; публикацию (включая push переписанной ветки) выполняет контроллер.
- C2. Цель rebase — только B по правилу D1, никогда не «живой» `origin/main` (если B случайно совпадает с ним — допустимо).
- C3. Полный набор тестов агенты не запускают; исполнитель запускает только `scripts/agent-check --phase quick`, команды AC и один именованный тест AC6.
- C4. `.agent/project.json`, зависимости и CI не меняются (смены политики проверок нет).
- C5. Конфликт разрешается только по D4; ручная правка маркеров и `-X ours/theirs` запрещены.
- C6. `TEAM.json` (артефакт Triage) не редактируется; действуют критерии этого SPEC и PLAN.json (D7).
- C7. Для AC4 нужен git ≥ 2.38 (`merge-tree --write-tree`); в worktree git 2.43.0. Для AC6 нужен Python ≥ 3.12 (код 5 при «0 тестов» плюс проверка `Ran 1 test`); в worktree 3.12.3.

## Решения

- D1. База интеграции B — чистая функция двух входов: константы P = `513a91f5e0a25adea3a44e74db6fb9b15b230f05` (текущий `origin/main`, F1) и поля `integration_base` (I) из текущего `request.json`:
  - I пуст или предок P (в т. ч. `57923dc`, а также I = P) → B = P;
  - I — потомок P (контроллер закрепил более новый main) → B = полный SHA I, при условии `B:labels.json` = blob `14ee0ebf…`; иначе остановка и `--amendment`;
  - иначе (ветвление, неизвестный коммит) → остановка и `--amendment`.
  Правило реализует фрагмент **BASE** (PLAN.md), одинаковый в S1 и в командах AC2–AC4. Перезакрепить `integration_base` может только контроллер.
- D2. button = `Reload items`. Основание — правило BRIEF «остальные значения не менять», применённое к ветке, в которую идёт слияние: `5f22a42` уже в main, его откат изменил бы чужое значение. Заголовок коммита — лишь описание; согласования владельца по кнопке в контракте нет (`owner_answers=null`), и оно не используется. Вариант «оставить Refresh» отвергнут.
- D3. Интеграция через `git rebase "$B"`, не merge-коммит: история линейная, B — предок HEAD (R2, R3). Push переписанной ветки делает контроллер (C1).
- D4. Разрешение конфликта: `labels.json` пересоздаётся из `B:labels.json` одной побайтовой заменой `Draft` → `Ready` с проверкой «ровно одно вхождение» (PLAN S2). Результат равен F5.
- D5. Новые тесты не добавляются: область BRIEF — одно значение в `labels.json`; существующий тест F7 уже проверяет вывод подписей на странице, не завязываясь на конкретные тексты.
- D6. UAT не нужен (needs_uat=false): BRIEF прямо исключает ручной UAT; видимое изменение — одно слово статуса; кнопка сохраняется из B; код страницы не меняется (F6); байты `labels.json` проверяются точным blob (AC1), а вывод подписей на странице — автоматическим тестом F7 (AC6 и полный набор в Verify).
- D7. Критерии заменены: TEAM AC1 → AC1; TEAM AC2 → AC2 + AC3; `request.team.verification` с `git diff 2561257… -- labels.json` и упоминание `Refresh` в `team.reason`/`TEAM.json` не используются (I2).
- D8. Маршрут `standard`: правка механическая, но включает rebase на новую базу и разрешение конфликта по правилу.
- D9. Проверки привязаны к выбранной B, а не к `git merge-base HEAD origin/main`: AC2 требует B предком HEAD, AC3 сравнивает пути с B, AC4 проверяет линейность `B..HEAD` и отдельно — бесконфликтное слияние с текущим `origin/main`. Исполнитель и ревьюер вычисляют B заново фрагментом BASE из своего `request.json`; исполнитель записывает B в отчёт.
- D10. P обновлён с `fdbf1e4` на `513a91f` (I6), а не оставлен: (а) Verify тогда проверяет код, который реально в main (`app.py` переписан в `3018963`), и включает тест страницы F7, которого нет в `fdbf1e4`; (б) разрыв с main сокращается до нуля на момент плана (урок «target branch advanced»). Отвергнутая альтернатива — «B = живой `origin/main` в момент работы»: ревьюер не смог бы вычислить ту же B из контракта, а каждое продвижение main между Work и Review ломало бы AC2/AC3. Дальнейшие продвижения main без изменения `labels.json` не требуют перепланирования: AC4 проверяет совместимость, остальное — цикл слияния контроллера (A5).
- D11. Восстановление после прерванной попытки (I3): S1 начинается с `git rebase --abort`, если rebase не завершён, и требует ветку `feature/canary-01-0k1`. Это безопасно: до окончания rebase ссылка ветки не меняется, а S2 полностью воспроизводим.
- D12. AC6 — один именованный тест F7 у исполнителя (разрешено C3): ранняя автоматическая проверка видимого результата до полного набора в Verify.

## Допущения (не блокируют работу)

- A1. Владелец хочет итоговые подписи в виде, как в main, плюс только новый статус: `Ready` / `Reload items` (BRIEF и D2). Это явно показано в отчёте для утверждения плана; отказ с указанием `Refresh` вернёт задачу на перепланирование.
- A2. Задачи canary, попадающие в main до слияния, не трогают `labels.json` (ветка `origin/feature/canary-02-10z` его не меняет). Если тронут — S1 остановит работу с `--amendment`, либо AC4/контроллер обнаружит конфликт.
- A3. `git fetch origin` доступен исполнителю и ревьюеру. Если нет — AC4 даёт ненулевой код и записывается как «не проверено», а не как пройденный.
- A4. Сервер вручную не запускается: подписи полностью определяются байтами `labels.json` (AC1), а их вывод на `/` проверяет тест F7 (AC6).
- A5. Если main продвинется после Work без изменения `labels.json`, слияние без конфликта обеспечивает цикл контроллера «rebase и свежий Verify» (по тексту урока); перепланирование не требуется.
- A6. Прерванный rebase I3 считается незавершённой попыткой, а не результатом: проверок и handoff по нему в контракте нет (`checks=null`).

## Критерии приёмки

`BASE` — фрагмент из PLAN.md (D1), вставляемый дословно в начало команды; он задаёт `$B` или завершается ненулевым кодом.

- AC1 (R1). `labels.json` в HEAD побайтно равен F5: `test "$(git rev-parse HEAD:labels.json)" = 89b9bb8f13167ce927f4bca8912a103a2941360f && python3 -I -c 'import json;assert json.load(open("labels.json"))=={"badge":"Ready","button":"Reload items"}'` — код 0.
- AC2 (R2). `BASE && git merge-base --is-ancestor "$B" HEAD && git merge-base --is-ancestor 513a91f5e0a25adea3a44e74db6fb9b15b230f05 HEAD && git merge-base --is-ancestor 5f22a42dd5e8cbf17890d7444c16ff87186cb09a HEAD` — код 0.
- AC3 (R4). `BASE && git merge-base --is-ancestor "$B" HEAD && test "$(git rev-parse "$B:labels.json")" = 14ee0ebf25856d061866cdb79ec0f413f36741b9 && test "$(git diff --name-only "$B" HEAD -- . ':(exclude).agent/tasks/5ae6e61d-c598-4526-8e53-2230864c3ba8')" = labels.json` — код 0.
- AC4 (R3). `BASE && git merge-base --is-ancestor "$B" HEAD && test -z "$(git rev-list --merges "$B..HEAD")" && git fetch origin && git merge-tree --write-tree HEAD origin/main >/dev/null` — код 0.
- AC5 (R5). `scripts/agent-check --phase quick` — код 0 у исполнителя; полный набор `python3 -m unittest discover -s tests -v` — ok в Verify контроллера.
- AC6 (R6). `out=$(python3 -m unittest discover -s tests -p test_reservations_http.py -k test_ac11_root_page_and_health_unchanged -v 2>&1); rc=$?; printf '%s\n' "$out"; test $rc -eq 0 && printf '%s\n' "$out" | grep -q '^Ran 1 test'` — код 0 (ровно один тест, OK).

Проверка логики (архитектор, на висячих объектах, без изменения веток, индекса и дерева): при I = `57923dc` правильный результат поверх P проходит AC1–AC4; результат по ред. 2 (поверх `fdbf1e4`) проваливает AC2–AC4; при I = N (потомок P) результат только поверх P проваливает AC2–AC4, а результат поверх N проходит; при I пустом B = P; при расходящемся I BASE возвращает код 1. AC5/AC6 не запускались: в текущем HEAD нет кода B, а запуск — работа исполнителя.

## Ответ на возражения

- Спор generation 24 (ред. 2): замечаний нет (`DEBATE_FINDINGS.json` = `[]`).
- Спор generation 22: F1 [major] «проверять выбранную B» — сохраняется в D9 и подтверждён проверкой логики выше с новой P; F2 [minor] «убрать неподтверждённую приёмку кнопки» — сохраняется в D2/D6 и отчёте владельцу.
- Поправка исполнителя generation 21 (перезакрепить базу, заменить AC2, замена в файле из main, отказ от `Refresh`) — сохраняется в D1, AC1–AC3, D4, D2.

## Вне области

Код (`app.py`, `api.py`), тесты, CI, `.agent/project.json`, `notes/`, дизайн и новые зависимости.
