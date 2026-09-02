# TubeAiFolw Web-development architecture

TubeAiFolw remains a Vue 3 Web UI plus a localhost FastAPI Engine during active
development. The Web transport is a development shell, not a place for workflow,
AI, or FFmpeg business logic. A future Tauri shell can launch the same Engine and
reuse its typed API without rewriting production workflows.

## Product surfaces

- **Projects** is the primary long-form production surface. A project owns script,
  narration, subtitles, scenes, assets, timeline, renders, logs, and exports.
- **Tools** preserves the existing segmented voice generation, local video merge,
  and digital-human workflows. These routes remain backward compatible while their
  outputs gain optional project integration.
- **Settings and providers** expose local runtime configuration and stable provider
  metadata. Provider-specific behavior must stay behind Engine adapters.

## Engine boundaries

```text
Vue Web UI
  -> typed API client
FastAPI API
  -> persisted TaskRun / workflow entry
Domain services
  -> provider registry / integrations / FFmpeg infrastructure
SQLite + project directory artifacts
```

The production app registers both project routes and compatible tool routes. Tests
must validate the actual `app.main` route contract so a feature cannot exist only in
an isolated test router.

## Compatibility rules

1. Existing `/api/tools/*`, `/api/voices`, and `/api/avatars` contracts remain valid.
2. Existing global SQLite data remains authoritative during the transition.
3. Every project also writes an atomic, secret-free `project.json` descriptor and
   uses a self-contained directory layout.
4. Existing legacy TTS ids remain accepted, while the provider registry exposes
   stable qualified ids such as `tts.index_tts`.
5. SQLite migrations create a consistent backup before applying a newer schema.
6. Third-party secrets are encrypted with Windows DPAPI; SQLite stores credential ids.

## Next implementation increments

1. Add Scene locks and version history without replacing existing VisualScene rows.
2. Move each long-running tool onto the shared persisted Job protocol.
3. Integrate local asset indexing and visual matching into the project workflow.
4. Add scene preview, partial timeline invalidation, and quality score dimensions.
5. Add the Tauri desktop shell only after the localhost Engine contract is stable.

The executable provider, workflow-step, configuration, and artifact contracts used for
these increments are documented in [extension-foundations.md](extension-foundations.md).
