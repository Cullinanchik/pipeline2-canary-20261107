# Synthetic canary Development Pipeline

Work only in this task's own repository/worktree/branch. No production repositories or services.
The controller owns transitions, retries, publication and approvals. Never move tasks, approve work,
run step_complete, push or merge. Read the current `.agent/runtime/<task-id>/request.json`, its
`role` contract and the task BRIEF before acting. Each role has a fresh native session.
If this is a bootstrap session without a request, do no work and reply `ок`.
The brief is synthetic but the role output must be real, complete and validated.
During development use only `scripts/agent-check --phase quick` or individually selected tests.
Full tests run only in controller Verify after a committed valid handoff and settled native session.
Review reads saved checks. Commit task-owned documents/code before the final quick check/handoff.
Run `scripts/pipeline-report --task <task-id>` according to request.role, including required report flags.
Do not fabricate task context, owner approvals, test evidence, artifacts or completion.
Do not inspect credentials or change any system configuration. All application data is synthetic.
Answer in Russian. Title must describe the actual task, preserving scenario prefix.
