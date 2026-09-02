# Extension foundations

TubeAiFolw keeps its public API and persisted stage ids stable while internal
implementations evolve behind registries and typed contracts.

## Provider boundary

`ProviderRegistry` owns both stable metadata and an optional executable runtime.
Business services resolve a category-specific runtime instead of branching on provider
ids. Provider-specific validation, command construction, and execution belong in the
runtime adapter. Metadata remains safe to expose to the UI.

Adding a provider should therefore require:

1. metadata and capabilities;
2. one category-specific runtime adapter;
3. configuration and contract tests;
4. no provider-id condition in workflow or API code.

## Workflow boundary

Persisted `TaskRun.current_stage` values map to registered `WorkflowStep` ids.
`WorkflowGraph` executes steps and persists every transition through the existing worker
callback. Steps declare resource class, dependencies, logical input/output artifacts, and
cache eligibility. These declarations are scheduling metadata; current serial execution
is intentionally unchanged.

The worker resolves a `WorkflowRuntime` from `WorkflowRegistry`. New workflows must not
add another dispatch branch to the worker.

## Artifact boundary

Project artifacts use project-relative paths, atomic replacement, SHA-256 verification,
and stable input signatures. `ArtifactStore` is shared by the visual-enrichment pipeline
and future application workflows. Critical project descriptors, manifests, timelines,
subtitle reports, visual-track reports, and quality reports are written atomically.

The global application database remains authoritative during the compatibility phase.
Moving generation history into a portable project database must use an explicit schema
version and migration; it must not introduce a second uncoordinated Scene model.

## Configuration boundary

`ProjectConfig` validates stable workflow and render-related fields while preserving
unknown provider extensions. Runtime snapshots remain versioned and secret-free. Services
should read project JSON through the shared loader rather than parsing `config_json`
independently.

## Compatibility rules

- Existing API routes and response shapes remain unchanged.
- Existing stage ids and qualified/legacy TTS provider ids remain accepted.
- Existing SQLite migrations and project directories remain readable.
- Refactors must preserve restart recovery and partial artifact reuse.
- New Scene, Timeline, Job, or Provider fields require a migration and contract tests.

