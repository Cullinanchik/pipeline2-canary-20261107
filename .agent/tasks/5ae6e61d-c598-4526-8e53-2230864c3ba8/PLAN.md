# Canary 01 · План: Draft → Ready поверх актуального main (ред. 2)

Задача `5ae6e61d-c598-4526-8e53-2230864c3ba8`, run `ffb63a25-af77-41f6-8033-1465f8678161`, generation 23,
context_digest `3f0439d6f5eded93a2937def51a43b1062c8805b33c3456d703d9cd39e9eaad4`. Требования, решения и критерии — в SPEC.md
(R1–R5, D1–D9, C1–C7, A1–A4, AC1–AC5). Маршрут `standard`; смены политики проверок нет (`.agent/project.json` не меняется).

Исполнитель выполняет шаги буквально, по порядку, из корня worktree. Каждая команда Bash идёт в новом shell, поэтому
`B` вычисляется заново фрагментом BASE в каждой команде, где он нужен. Альтернатив нет: при любом отклонении от
ожидаемого — остановиться, откатить по разделу «Откат» и подать
`scripts/pipeline-report --task 5ae6e61d-c598-4526-8e53-2230864c3ba8 --amendment FILE` с JSON `{reason, evidence, proposal}`.

Константы: P = `fdbf1e4203a8770c7148668e14de48a79b65dad5`; upstream-коммит кнопки `5f22a42dd5e8cbf17890d7444c16ff87186cb09a`;
blob upstream `labels.json` = `14ee0ebf25856d061866cdb79ec0f413f36741b9`; ожидаемый blob результата = `89b9bb8f13167ce927f4bca8912a103a2941360f`.

## Фрагмент BASE (правило D1; вставлять дословно)

Задаёт переменную `B` = выбранная база интеграции или завершается ненулевым кодом. Один и тот же фрагмент используется
в S1 и в командах AC2–AC4 у исполнителя и у ревьюера; `git merge-base HEAD origin/main` вместо него не использовать (D9).

```sh
P=fdbf1e4203a8770c7148668e14de48a79b65dad5 && I=$(python3 -I -c 'import json;print(json.load(open(".agent/runtime/5ae6e61d-c598-4526-8e53-2230864c3ba8/request.json")).get("integration_base") or "")') && if [ -z "$I" ] || git merge-base --is-ancestor "$I" "$P" 2>/dev/null; then B=$P; elif git merge-base --is-ancestor "$P" "$I" 2>/dev/null; then B=$(git rev-parse --verify "$I^{commit}"); else echo "integration_base $I diverges from $P" >&2; false; fi
```

Архитектор проверил логику фрагмента и команд AC2–AC4 на временных висячих коммитах (без изменения веток и рабочего дерева):
I = `57923dc` → B = P; правильный результат поверх P проходит AC1–AC4; контрпример оппонента (I = N — потомок P,
результат только поверх P) проваливает AC2, AC3 и AC4; результат поверх N при I = N проходит AC2/AC3; результат поверх
N при B = P проваливает AC3; неизвестный I → ненулевой код. Это проверка логики, а не выполнение плана.

## S1. Выбор базы интеграции B и предусловия (только чтение) — AC2

Файлы: `labels.json` (только чтение в B), `.agent/runtime/5ae6e61d-c598-4526-8e53-2230864c3ba8/request.json` (только чтение).

Команда (одной строкой BASE в начале; ненулевой код выхода → остановка и amendment):

```sh
git fetch origin || echo "fetch failed; continuing with local objects"
<BASE> && git cat-file -e "$P^{commit}" \
  && { test "$(git rev-parse "$B:labels.json")" = 14ee0ebf25856d061866cdb79ec0f413f36741b9 || { echo "labels.json changed upstream in $B"; false; }; } \
  && { test -z "$(git status --porcelain)" || { echo "worktree not clean"; false; }; } \
  && echo "B=$B" && echo "PRE=$(git rev-parse HEAD)"
```

Ожидается сейчас: `I` = `57923dc…` (предок P) → `B=fdbf1e4203a8770c7148668e14de48a79b65dad5`. Записать значения `B` и `PRE` —
они нужны в S2, S3 и в отчёте.

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
   только `.agent/tasks/5ae6e61d-c598-4526-8e53-2230864c3ba8/` (SPEC F3). Если rebase завершился без остановки — всё равно перейти к S3.

Запрещено: правка маркеров конфликта вручную, `-X ours`/`-X theirs`, `git merge`, правка любых файлов кроме `labels.json`,
перебазирование на `origin/main` или на что-либо, кроме B.

## S3. Проверка критериев и quick-check — AC1, AC2, AC3, AC4, AC5

Файлы: `labels.json` (только чтение). Каждая команда должна завершиться с кодом 0 (`<BASE>` — фрагмент выше, дословно):

- B не изменилась: `<BASE> && test "$B" = <B из S1>` — иначе остановка и amendment (контракт сменился во время работы).
- AC1: `test "$(git rev-parse HEAD:labels.json)" = 89b9bb8f13167ce927f4bca8912a103a2941360f && python3 -I -c 'import json;assert json.load(open("labels.json"))=={"badge":"Ready","button":"Reload items"}'`
- AC2: `<BASE> && git merge-base --is-ancestor "$B" HEAD && git merge-base --is-ancestor fdbf1e4203a8770c7148668e14de48a79b65dad5 HEAD && git merge-base --is-ancestor 5f22a42dd5e8cbf17890d7444c16ff87186cb09a HEAD`
- AC3: `<BASE> && git merge-base --is-ancestor "$B" HEAD && test "$(git rev-parse "$B:labels.json")" = 14ee0ebf25856d061866cdb79ec0f413f36741b9 && test "$(git diff --name-only "$B" HEAD -- . ':(exclude).agent/tasks/5ae6e61d-c598-4526-8e53-2230864c3ba8')" = labels.json`
- AC4: `<BASE> && git merge-base --is-ancestor "$B" HEAD && test -z "$(git rev-list --merges "$B..HEAD")" && git fetch origin && git merge-tree --write-tree HEAD origin/main >/dev/null`
  (если упал только `git fetch origin` — записать AC4 как «не проверено», не как пройденный; SPEC A3).
- AC5: `scripts/agent-check --phase quick`; сохранить результат для `--checks` по контракту запроса.
- `git status --porcelain` пуст (кроме игнорируемого `.agent/runtime/`).

Полный набор тестов (`python3 -m unittest discover -s tests -v`) исполнитель НЕ запускает — это Verify контроллера (C3).

## S4. Handoff — AC5

Файлы: `.agent/tasks/5ae6e61d-c598-4526-8e53-2230864c3ba8/` (только отчёт владельцу по пути из запроса исполнителя).

Записать отчёт владельцу по схеме своего `request.owner_reporting`, указав `B`, `PRE`, новый HEAD и коды выхода AC1–AC5
(без утверждений о согласованиях владельца, которых нет в запросе), и выполнить
`scripts/pipeline-report --task 5ae6e61d-c598-4526-8e53-2230864c3ba8` с флагами, которые требует запрос
(`--owner-report`, `--checks`). Push, merge, step_complete и перемещение задачи не выполнять: контроллер сам публикует
переписанную ветку, запускает Verify и запрашивает приёмку результата.

## Откат и восстановление

- Во время rebase при любом неожиданном конфликте/ошибке: `git rebase --abort` (HEAD возвращается в `PRE`).
- После завершённого rebase, если AC1–AC4 не проходят: `git reset --hard <PRE>` (только локальный worktree; исходное
  состояние также сохранено в `origin/feature/canary-01-0k1`), затем amendment с выводом команд.
- Если main снова изменит `labels.json` до слияния: S1 остановит работу, либо AC4/контроллер обнаружит конфликт и
  запустит Fix с новой базой — план применяется заново по правилу D1.

## Риски

- Main продвинется после выбора B → AC4 (`merge-tree` с текущим `origin/main`) или контроллер обнаружит конфликт; повтор по D1.
- Rebase на неверную базу: на предка B — ловит AC2 (B не предок HEAD); на потомка B (например, «живой» `origin/main`) — ловит AC3
  (лишние пути относительно B); ручная правка маркеров — ловит AC1 (точный blob).
- Контроллер перезакрепит базу между Work и Review → у ревьюера BASE даст новую B и AC2/AC3 провалятся: это верный сигнал
  «результат устарел, нужен Fix с новой базой» (SPEC D9).
- Устаревший AC2 в `TEAM.json` может сбить ревьюера → SPEC D7 прямо заменяет критерии.
- Переписанная история требует принудительной публикации ветки → это действие контроллера (C1); откат — через `PRE`.
