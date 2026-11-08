# Canary 01 · План: Draft → Ready поверх актуального main (ред. 3)

Задача `5ae6e61d-c598-4526-8e53-2230864c3ba8`, run `40e30778-9ab7-4b99-a45c-772a90f7c37a`, generation 27,
context_digest `5f0eee644d24b661f78a795d2715f0a5b9f0841a59eb5cfa036eb4f5608f9964`. Требования, решения и критерии — в SPEC.md
(R1–R6, D1–D12, C1–C7, A1–A6, AC1–AC6, проверка целостности I1–I7). Маршрут `standard`; смены политики проверок нет
(`.agent/project.json` не меняется). Отличия от ред. 2: P = `513a91f…` вместо `fdbf1e4…` (D10), восстановление после
прерванного rebase в S1 (D11), именованный тест страницы AC6 (D12), уточнён откат.

Исполнитель выполняет шаги буквально, по порядку, из корня worktree. Каждая команда Bash идёт в новом shell, поэтому
`B` вычисляется заново фрагментом BASE в каждой команде, где он нужен. Альтернатив нет: при любом отклонении от
ожидаемого — остановиться, откатить по разделу «Откат» и подать
`scripts/pipeline-report --task 5ae6e61d-c598-4526-8e53-2230864c3ba8 --amendment FILE` с JSON `{reason, evidence, proposal}`.

Константы: P = `513a91f5e0a25adea3a44e74db6fb9b15b230f05`; upstream-коммит кнопки `5f22a42dd5e8cbf17890d7444c16ff87186cb09a`;
blob upstream `labels.json` = `14ee0ebf25856d061866cdb79ec0f413f36741b9`; ожидаемый blob результата = `89b9bb8f13167ce927f4bca8912a103a2941360f`.

## Фрагмент BASE (правило D1; вставлять дословно)

Задаёт переменную `B` = выбранная база интеграции или завершается ненулевым кодом. Один и тот же фрагмент используется
в S1 и в командах AC2–AC4 у исполнителя и у ревьюера; `git merge-base HEAD origin/main` вместо него не использовать (D9).

```sh
P=513a91f5e0a25adea3a44e74db6fb9b15b230f05 && I=$(python3 -I -c 'import json;print(json.load(open(".agent/runtime/5ae6e61d-c598-4526-8e53-2230864c3ba8/request.json")).get("integration_base") or "")') && if [ -z "$I" ] || git merge-base --is-ancestor "$I" "$P" 2>/dev/null; then B=$P; elif git merge-base --is-ancestor "$P" "$I" 2>/dev/null; then B=$(git rev-parse --verify "$I^{commit}"); else echo "integration_base $I diverges from $P" >&2; false; fi
```

## S1. Восстановление, выбор базы B и предусловия (только чтение истории) — AC2

Файлы: `labels.json` (только чтение в B), `.agent/runtime/5ae6e61d-c598-4526-8e53-2230864c3ba8/request.json` (только чтение).

1. Если предыдущая попытка оставила незавершённый rebase (D11), отменить его — ссылка ветки при этом не меняется:

   ```sh
   if [ -d "$(git rev-parse --git-path rebase-merge)" ] || [ -d "$(git rev-parse --git-path rebase-apply)" ]; then git rebase --abort; fi
   test "$(git symbolic-ref --short HEAD)" = feature/canary-01-0k1 || { echo "not on feature/canary-01-0k1"; false; }
   ```

2. Выбрать B и проверить предусловия (одной командой, BASE в начале; ненулевой код → остановка и amendment):

   ```sh
   git fetch origin || echo "fetch failed; continuing with local objects"
   <BASE> && git cat-file -e "$P^{commit}" \
     && { test "$(git rev-parse "$B:labels.json")" = 14ee0ebf25856d061866cdb79ec0f413f36741b9 || { echo "labels.json changed upstream in $B"; false; }; } \
     && { test -z "$(git status --porcelain)" || { echo "worktree not clean"; false; }; } \
     && echo "B=$B" && echo "PRE=$(git rev-parse HEAD)"
   ```

Ожидается сейчас: `I` = `57923dc…` (предок P) → `B=513a91f5e0a25adea3a44e74db6fb9b15b230f05`. Записать значения `B` и `PRE` —
они нужны в S2, S3 и в отчёте.

## S2. Rebase на B и восстановление labels.json — AC1, AC2, AC3

Файлы: `labels.json`; коммиты задачи переносятся без изменений содержимого, кроме `labels.json`.

1. `git rebase <B>` (подставить SHA из S1). Ожидаемо rebase остановится на коммите
   «Canary 01 · Заменить статус Draft на Ready в labels.json» с `CONFLICT (content)` только в `labels.json` (SPEC F3).
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
   только `.agent/tasks/5ae6e61d-c598-4526-8e53-2230864c3ba8/`, которого нет в upstream (SPEC F3). Если rebase завершился без
   остановки — всё равно перейти к S3.

Запрещено: правка маркеров конфликта вручную, `-X ours`/`-X theirs`, `git merge`, правка любых файлов кроме `labels.json`,
перебазирование на `origin/main` или на что-либо, кроме B.

## S3. Проверка критериев, quick-check и тест страницы — AC1, AC2, AC3, AC4, AC5, AC6

Файлы: `labels.json` (только чтение). Каждая команда должна завершиться с кодом 0 (`<BASE>` — фрагмент выше, дословно):

- B не изменилась: `<BASE> && test "$B" = <B из S1>` — иначе остановка и amendment (контракт сменился во время работы).
- AC1: `test "$(git rev-parse HEAD:labels.json)" = 89b9bb8f13167ce927f4bca8912a103a2941360f && python3 -I -c 'import json;assert json.load(open("labels.json"))=={"badge":"Ready","button":"Reload items"}'`
- AC2: `<BASE> && git merge-base --is-ancestor "$B" HEAD && git merge-base --is-ancestor 513a91f5e0a25adea3a44e74db6fb9b15b230f05 HEAD && git merge-base --is-ancestor 5f22a42dd5e8cbf17890d7444c16ff87186cb09a HEAD`
- AC3: `<BASE> && git merge-base --is-ancestor "$B" HEAD && test "$(git rev-parse "$B:labels.json")" = 14ee0ebf25856d061866cdb79ec0f413f36741b9 && test "$(git diff --name-only "$B" HEAD -- . ':(exclude).agent/tasks/5ae6e61d-c598-4526-8e53-2230864c3ba8')" = labels.json`
- AC4: `<BASE> && git merge-base --is-ancestor "$B" HEAD && test -z "$(git rev-list --merges "$B..HEAD")" && git fetch origin && git merge-tree --write-tree HEAD origin/main >/dev/null`
  (если упал только `git fetch origin` — записать AC4 как «не проверено», не как пройденный; SPEC A3).
- AC5: `scripts/agent-check --phase quick`; сохранить результат для `--checks` по контракту запроса.
- AC6: `out=$(python3 -m unittest discover -s tests -p test_reservations_http.py -k test_ac11_root_page_and_health_unchanged -v 2>&1); rc=$?; printf '%s\n' "$out"; test $rc -eq 0 && printf '%s\n' "$out" | grep -q '^Ran 1 test'`
  (один именованный тест из B, SPEC F7; это не полный набор).
- `git status --porcelain` пуст (игнорируются `.agent/runtime/`, `__pycache__/`).

Полный набор тестов (`python3 -m unittest discover -s tests -v`) исполнитель НЕ запускает — это Verify контроллера (C3).

## S4. Handoff — AC5

Файлы: `.agent/tasks/5ae6e61d-c598-4526-8e53-2230864c3ba8/` (только отчёт владельцу по пути из запроса исполнителя).

Записать отчёт владельцу по схеме своего `request.owner_reporting`, указав `B`, `PRE`, новый HEAD и коды выхода AC1–AC6
(без утверждений о согласованиях владельца, которых нет в запросе); закоммитить его, если запрос требует отслеживаемый
файл; выполнить `scripts/pipeline-report --task 5ae6e61d-c598-4526-8e53-2230864c3ba8` с флагами, которые требует запрос
(`--owner-report`, `--checks`). Push, merge, step_complete и перемещение задачи не выполнять: контроллер сам публикует
переписанную ветку, запускает Verify и запрашивает приёмку результата.

## Откат и восстановление

- Во время rebase при любом неожиданном конфликте/ошибке: `git rebase --abort` (HEAD возвращается в `PRE`).
- После завершённого rebase, если AC1–AC4 или AC6 не проходят: `git reset --hard <PRE>` (только локальный worktree;
  `PRE` также виден в `git reflog`; `origin/feature/canary-01-0k1` = `0afc426` — старое состояние без документов плана, для
  отката не использовать), затем amendment с выводом команд.
- Если сессия прервана посреди rebase: следующая роль выполняет S1 п. 1 (`git rebase --abort`) и начинает заново (D11).
- Если main снова изменит `labels.json` до слияния: S1 остановит работу, либо AC4/контроллер обнаружит конфликт и
  запустит Fix с новой базой — план применяется заново по правилу D1.

## Риски

- Main продвинется после выбора B без изменения `labels.json` → AC4 остаётся зелёным, ветку к слиянию подтягивает цикл
  контроллера «rebase и свежий Verify» (SPEC A5, D10); с изменением `labels.json` → остановка S1/AC4 и повтор по D1.
- Rebase на неверную базу: на предка B — ловят AC2/AC3/AC4 (B не предок HEAD; проверено для результата поверх `fdbf1e4`);
  на потомка B (например, «живой» `origin/main`) — ловит AC3 (лишние пути относительно B); ручная правка маркеров — AC1.
- Контроллер перезакрепит базу между Work и Review → у ревьюера BASE даст новую B и AC2/AC3 провалятся: это верный сигнал
  «результат устарел, нужен Fix с новой базой» (SPEC D9).
- Устаревшие AC2/`verification` в `TEAM.json` и `request.team` могут сбить ревьюера → SPEC I2, D7 прямо заменяют критерии.
- Повторное прерывание посреди rebase → S1 п. 1 восстанавливает исходное состояние ветки (D11).
- AC6 поднимает тестовый сервер на эфемерном порту `127.0.0.1`; любой ненулевой код AC6 (в том числе сбой окружения)
  записывается как провал с полным выводом и ведёт к откату и amendment, а не к «не проверено» или «пройдено».
- Переписанная история требует принудительной публикации ветки → это действие контроллера (C1); откат — через `PRE`.
