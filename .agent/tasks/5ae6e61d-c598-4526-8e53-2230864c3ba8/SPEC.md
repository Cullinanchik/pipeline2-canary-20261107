# Canary 01 · Тривиальная замена статуса

Источник: `.agent/runtime/5ae6e61d-c598-4526-8e53-2230864c3ba8/context/52bedf6f19cf88ee6c871122ec0351d76b599d06aec3af5badae9d01caa1ed7e.json` (поле content), текущий request.json.

Область изменения: только `labels.json`, единственная замена `Draft` → `Ready`.

- AC1: значение badge равно Ready.
- AC2: все остальные байты labels.json и исходные файлы неизменны; button остаётся Refresh.

Логика, зависимости и дизайн не меняются. Ручной UAT не нужен по BRIEF.
