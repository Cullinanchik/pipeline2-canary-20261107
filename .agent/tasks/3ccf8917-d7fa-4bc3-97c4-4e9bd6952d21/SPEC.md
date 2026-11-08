# Canary 09 · Замена статуса параллельной задачи B

Цель: заменить pending на completed в notes/parallel-b.txt.

- AC1: В notes/parallel-b.txt единственное pending заменено на completed; итоговые байты: Synthetic note B: completed.\n.
- AC2: Остальные байты целевого файла и другие файлы приложения не изменены.
- AC3: UAT не требуется; работа ограничена текущим worktree.

Область: только notes/parallel-b.txt; служебные документы задачи хранятся отдельно.
Источник: .agent/runtime/3ccf8917-d7fa-4bc3-97c4-4e9bd6952d21/context/c9cbc855c6364ea4b557c800b26f3e5c7210948e5da8fcc1cccc9c295c87471a.json
