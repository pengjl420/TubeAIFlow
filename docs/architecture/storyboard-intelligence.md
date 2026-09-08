# Storyboard intelligence architecture

TubeAiFolw uses a local-first, cloud-assisted pipeline for transcript-to-visual planning.

## Processing stages

1. Deterministic transcript validation preserves every source character and timing unit.
2. The configured LLM groups consecutive narration units into visual semantic scenes.
3. Each scene becomes a provider-neutral structured visual brief.
4. A deterministic compiler produces image-generation prompts from that brief.
5. Downstream stock, archive, chart, image and video providers consume the same scene facts.

TTS segments, subtitle cues and visual scenes remain separate concepts. A rough visual hint
created during TTS segmentation may inform planning, but does not define the final scene.

## Routing modes

- `local`: use the llama.cpp-compatible local model only.
- `hybrid`: use the local model first, then escalate low-confidence or high identity-risk
  storyboard batches to the configured cloud provider. A local service failure also falls
  back to cloud when a BYOK credential is available.
- `cloud`: use the configured cloud provider for every LLM operation.

The default is `hybrid`. Identical structured requests are cached by provider, model,
prompts, task and schema. API keys are never part of the cache key or artifact.

## Long-form context policy

Short transcripts are included as-is. Long transcripts use bounded opening and closing
excerpts plus consecutive local cues. This prevents the complete 20-60 minute transcript
from being resent with every scene batch. Future chapter summaries can replace the bounded
excerpt without changing the provider contract.

## Persisted output

Storyboard artifacts include the selected provider, model and routing decisions. Each scene
stores a structured `visual_brief`, deterministic `image_prompt`, `negative_prompt`, source
recommendation, confidence and factual/identity risk metadata. Existing scene JSON remains
valid because new fields have migration-safe defaults.
