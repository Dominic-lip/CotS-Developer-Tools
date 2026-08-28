# TASK-009 — Compile, Validation and Diagnostics

## Objective
Ensure an agent can determine whether its own Unreal changes are actually valid.

## Target capabilities
Blueprint compile; project/editor build status; asset/folder validation; map check; broken-reference discovery; relevant Output Log retrieval/filtering; test log isolation; machine-readable errors/warnings.

## Acceptance criteria
Intentionally create a disposable validation/compile failure, prove the agent detects the correct failure, repair it, and prove the clean result.
