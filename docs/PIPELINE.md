# Core Pipeline

`PDFFastParser.parse()` runs one isolated run directory under the configured
output root. The directory contains Stage 1-9 artifacts, provider raw and
selected prediction artifacts, the canonical document, rendered Markdown, and
the structure audit.

Provider execution is explicit in Core. `run_core_pipeline(...,
execute_providers=False)` can produce the planning artifacts without starting
heavyweight providers; production parsing passes `True` together with a
validated Registry, provider configuration, and runtime normalizer.

The executor initializes each provider once per run, groups tasks into
deterministic escalation waves, closes every provider in `finally`, and writes
`production_execution_manifest.json` plus `selected_prediction_index.json`.
Any missing or runtime-disabled provider referenced by the frozen policy fails
configuration validation before provider resolution.

The final completion condition is the Stage 10.2.1 structure audit. A run is
not considered successful merely because a provider returned text.
