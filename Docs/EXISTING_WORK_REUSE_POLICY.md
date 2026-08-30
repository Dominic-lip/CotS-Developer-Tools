# Existing-Work Reuse Policy

## Principle
CotS production development is greenfield in architecture, not amnesiac in implementation. Existing work is checked **just in time for the subsystem currently being built**. The goal is to avoid duplicated engineering and credit burn without forcing the production roadmap to follow legacy shard order.

## Known sources
- `C:\Dev\Shardlands` — primary local donor/reference; READ-ONLY. Local state may be newer than GitHub and may contain unpushed work.
- `Dominic-lip/Shardlands` — remote history/reference.
- `Dominic-lip/CotS-Website` — public/editorial/account-facing web work and integration assumptions.
- `Dominic-lip/CotS-Platform-API` — platform/backend/database/auth/API work.
- `Dominic-lip/CotS-Game` / `C:\Dev\CotS` — production destination and any already-landed production work.
- Relevant specs, generated data, migration reports and prior decisions in `CotSDeveloperTools`.

## Just-in-time procedure
For every `TASK-100+` subsystem:

1. **Reconcile current production state.** Determine what already exists in `C:\Dev\CotS` and what is actually verified.
2. **Search before reading broadly.** Use filenames, symbols, modules, commit history, docs and manifests to locate likely donor work. Do not read thousands of unrelated files just because they exist.
3. **Inspect the relevant donor slice deeply enough to understand it.** Follow dependencies, authority assumptions, data identities, UE version/API usage, tests, persistence and coupling.
4. **Check cross-system sources only when relevant.** Identity/server/database tasks must inspect Website/Platform-API contracts; world simulation tasks need not repeatedly crawl website code.
5. **Classify significant donor material:**
   - `REUSE_DIRECTLY` — compatible and production-worthy with minimal change.
   - `ADAPT` — valuable implementation, but architecture/API/dependency changes are required.
   - `REIMPLEMENT` — concept is useful but carrying code forward would create more risk/debt than rebuilding.
   - `REFERENCE_ONLY` — useful behavior/specification, not suitable production code.
   - `LEAVE` — obsolete, experiment, duplicate or out of scope.
6. **Record evidence and decision.** Write/update `Docs/Production/Reuse/TASK-<id>.md` with source paths/revisions, classification, destination and validation evidence.
7. **Migrate/adapt into production, never in place.** Shardlands stays read-only. Unreal assets must use safe Unreal-aware migration/import operations rather than blind filesystem copying.
8. **Validate as production code.** Compile, automate, live-verify and re-inspect. Reuse is not accepted merely because donor code once worked.

## Freshness and local donor state
When `C:\Dev\Shardlands` and remote GitHub differ, treat the local donor as potentially newer evidence. Inspect local Git status/branches/paths without modifying them. Never clean/reset/checkout the donor to make inspection easier.

## Efficiency rule
Do not perform a complete full-repository audit before every task. Build and maintain a shallow source index in `TASK-100`; then deepen only the subsystem currently under development. This is both faster and cheaper than repeatedly rediscovering or rewriting work.

## Compatibility rule
Production architecture wins over legacy shape. Reuse does not mean preserving old module boundaries, naming or technical debt. Preserve proven behavior and valuable implementation where sensible while conforming it to current authority, persistence, networking, data and testing conventions.

## Website/platform rule
Website and Platform API repositories are integration peers, not dumping grounds. Read them whenever game identity, authentication, characters, server discovery, persistence or public account state are involved. Cross-repository mutations require explicit task authorization and must preserve compatibility or include a documented migration plan.
