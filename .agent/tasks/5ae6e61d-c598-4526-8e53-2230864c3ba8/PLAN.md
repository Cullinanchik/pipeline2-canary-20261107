# Canary 01 · План: Draft → Ready поверх актуального main

Задача `5ae6e61d-c598-4526-8e53-2230864c3ba8`, run `00fbd42c-fd39-415a-ae49-9a9a19976a4f`, generation 21,
context_digest `caf29abedb18ccf78dc15a95f0b4cb918cbb581f1e589776bc0a18f67cfe46cb`. Требования, решения и критерии — в SPEC.md
(R1–R5, D1–D8, C1–C7, A1–A4, AC1–AC5). Маршрут `standard`; смены политики проверок нет (`.agent/project.json` не меняется).

Исполнитель выполняет шаги буквально, по порядку, из корня worktree. Каждая команда Bash запускается в новом shell,
поэтому `P`/`B` задаются заново в каждой команде, где они нужны. Альтернатив нет: при любом отклонении от
ожидаемого — остановиться, откатить по разделу «Откат» и подать `scripts/pipeline-report --task 5ae6e61d-c598-4526-8e53-2230864c3ba8 --amendment FILE`
с JSON `{reason, evidence, proposal}`.

Константы: P = `fdbf1e4203a8770c7148668e14de48a79b65dad5`; upstream-коммит кнопки `5f22a42dd5e8cbf17890d7444c16ff87186cb09a`;
blob upstream `labels.json` = `14ee0ebf25856d061866cdb79ec0f413f36741b9`; ожидаемый blob результата = `89b9bb8f13167ce927f4bca8912a103a2941360f`.

## S1. Выбор базы интеграции B и предусловия (только чтение) — AC2

Файлы: `labels.json` (только чтение в B), `.agent/runtime/5ae6e61d-c598-4526-8e53-2230864c3ba8/request.json` (только чтение).

Команда (печатает `B=<sha>`; ненулевой код выхода → остановка и amendment):

```sh
P=fdbf1e4203a8770c7148668e14de48a79b65dad5
I=$(python3 -I -c 'import json;print(json.load(open(".agent/runtime/5ae6e61d-c598-4526-8e53-2230864c3ba8/request.json")).get("integration_base") or "")')
git fetch origin || echo "fetch failed; continuing with local objects"
git cat-file -e "$P^{commit}" || exit 1
if [ -z "$I" ] || git merge-base --is-ancestor "$I" "$P"; then B=$P
elif git merge-base --is-ancestor "$P" "$I"; then B=$I
else echo "integration_base $I diverges from $P"; exit 1; fi
test "$(git rev-parse "$B:labels.json")" = 14ee0ebf25856d061866cdb79ec0f413f36741b9 || { echo "labels.json changed upstream after $P"; exit 1; }
test -z "$(git status --porcelain)" || { echo "worktree not clean"; exit 1; }
echo "B=$B"; echo "PRE=$(git rev-parse HEAD)"
```

Ожидается сейчас: `I` = `57923dc…` (предок P) → `B=fdbf1e4…`. Запишите значения `B` и `PRE` — они нужны в S2 и в отчёте.

## S2. Rebase на B и восстановление labels.json — AC1, AC2, AC3

Файлы: `labels.json`; коммиты задачи переносятся без изменений содержимого, кроме `labels.json`.

1. `git rebase <B>` (подставить SHA из S1). Ожидаемо rebase остановится на коммите
   «Canary 01 · Заменить статус Draft на Ready в labels.json» с `CONFLICT (content)` только в `labels.json`.
2. Проверить `git diff --name-only --diff-filter=U`: вывод должен быть ровно `labels.json`. Иначе — `git rebase --abort` и amendment.
3. Пересоздать файл из базы одной точной заменой (D4):

   ```sh
   B=<sha из S1>
   git show "$B:labels.json" | python3 -I -c 'import sys;b=sys.stdin.buffer.read();assert b.count(b"Draft")==1;sys.stdout.buffer.write(b.replace(b"Draft",b"Ready",1))' > labels.json
   test "$(git hash-object labels.json)" = 89b9bb8f13167ce927f4bca8912a103a2941360f
   git add labels.json
   GIT_EDITOR=true git rebase --continue
   ```

4. Повторять пункты 2–3, пока rebase не завершится. Других конфликтов не ожидается: остальные коммиты задачи меняют
   только `.agent/tasks/5ae6e61d-c598-4526-8e53-2230864c3ba8/` (F3). Если rebase завершился без остановки — всё равно перейти к S3.

Запрещено: правка маркеров конфликта вручную, `-X ours`/`-X theirs`, `git merge`, правка любых файлов кроме `labels.json`,
перебазирование на `origin/main` вместо B.

## S3. Проверка критериев и quick-check — AC1, AC2, AC3, AC4, AC5

Файлы: `labels.json` (только чтение). Каждая команда должна завершиться с кодом 0:

- AC1: `test "$(git rev-parse HEAD:labels.json)" = 89b9bb8f13167ce927f4bca8912a103a2941360f && python3 -I -c 'import json;assert json.load(open("labels.json"))=={"badge":"Ready","button":"Reload items"}'`
- AC2: `git merge-base --is-ancestor fdbf1e4203a8770c7148668e14de48a79b65dad5 HEAD && git merge-base --is-ancestor 5f22a42dd5e8cbf17890d7444c16ff87186cb09a HEAD`
- AC3: `B=$(git merge-base HEAD origin/main); test "$(git diff --name-only "$B" HEAD -- . ':(exclude).agent/tasks/5ae6e61d-c598-4526-8e53-2230864c3ba8')" = labels.json && test "$(git rev-parse "$B:labels.json")" = 14ee0ebf25856d061866cdb79ec0f413f36741b9`
- AC4: `git fetch origin && git merge-tree --write-tree HEAD origin/main >/dev/null && test -z "$(git rev-list --merges "$(git merge-base HEAD origin/main)"..HEAD)"`
- AC5: `scripts/agent-check --phase quick`; сохранить результат для `--checks` по контракту запроса.
- `git status --porcelain` пуст (кроме игнорируемого `.agent/runtime/`).

Полный набор тестов (`python3 -m unittest discover -s tests -v`) исполнитель НЕ запускает — это Verify контроллера (C3).

## S4. Handoff — AC5

Файлы: `.agent/tasks/5ae6e61d-c598-4526-8e53-2230864c3ba8/` (только отчёт владельцу по пути из запроса исполнителя).

Записать отчёт владельцу по схеме своего `request.owner_reporting`, указав `B`, `PRE`, новый HEAD и коды выхода AC1–AC5,
и выполнить `scripts/pipeline-report --task 5ae6e61d-c598-4526-8e53-2230864c3ba8` с флагами, которые требует запрос
(`--owner-report`, `--checks`). Push, merge, step_complete и перемещение задачи не выполнять: контроллер сам публикует
переписанную ветку, запускает Verify и запрашивает приёмку результата.

## Откат и восстановление

- Во время rebase при любом неожиданном конфликте/ошибке: `git rebase --abort` (HEAD возвращается в `PRE`).
- После завершённого rebase, если AC1–AC4 не проходят: `git reset --hard <PRE>` (только локальный worktree; исходное
  состояние также сохранено в `origin/feature/canary-01-0k1`), затем amendment с выводом команд.
- Если main снова изменит `labels.json` до слияния: S1 остановит работу, либо контроллер получит конфликт слияния и
  запустит Fix с новой базой — план применяется заново по правилу D1.

## Риски

- Main продвинется после выбора B → возможен новый конфликт; закрыт правилом D1 и циклом контроллера.
- Исполнитель вручную правит маркеры или берёт `origin/main` → ловится AC1 (точный blob) и AC2/AC3.
- Устаревший AC2 в `TEAM.json` может сбить ревьюера → SPEC D7 прямо заменяет критерии.
- Переписанная история требует принудительной публикации ветки → это действие контроллера (C1).
