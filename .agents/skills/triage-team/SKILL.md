---
name: triage-team
description: Execute the current canary role using the controller's immutable request contract.
---
Read AGENTS.md and `.agent/runtime/<task-id>/request.json`. Follow `request.role` exactly;
that contract is the source of truth for allowed writes, required inputs/outputs and completion.
Never approve, advance stages, publish or merge. `scripts/pipeline-report` produces the handoff.
Quick checks only during implementation; full suites are controller-owned Verify.
