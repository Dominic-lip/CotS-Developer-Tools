# CotS Task Specification Format

Every substantial task should use the same agent-neutral structure.

## Required sections

### Objective
Single clear outcome.

### Context
Why the task exists and relevant prior state.

### Allowed scope
Files, repositories, Unreal projects and assets the agent may modify.

### Forbidden scope
Explicit no-touch areas.

### Requirements
Functional and architectural requirements.

### Procedure constraints
Safety, ordering, compatibility or inspection requirements.

### Validation
Commands/tests/editor checks that must actually run.

### Acceptance criteria
Observable conditions for completion.

### Deliverables
Code, reports, schemas, generated files or commits expected.

### Completion report
The agent must report changed files/assets, tests executed, errors/warnings, unverified assumptions and follow-up work.

## Rule
A task specification describes outcomes and constraints, not a long series of UI clicks. If deterministic UI manipulation is required repeatedly, build a tool for it.
