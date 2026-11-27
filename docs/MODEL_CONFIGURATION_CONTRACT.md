# Current model configuration contract

2026-11-27. Living API note; [verification](worklogs/rodina/2026-11-27_model-configuration-fixes/REPORT.md). This does not change locked rules or install official v2 governance.

`mini.parse_args(argv=None)` preserves normal command-line use and accepts an explicit argument list for embedding. `model_options_provided` is a frozen set of the seven model-setting destination names explicitly assigned by argparse. Equals-form and separated arguments are identical, including explicit values equal to defaults.

A JSON model configuration cannot be combined with those explicit settings. Untouched parser defaults are not conflicts. Programmatic namespaces without provenance treat actually present setting properties as explicit; callers constructing a namespace with default-filled properties can pass `model_options_provided=frozenset()` to identify default-derived values. Invalid provenance is rejected. Configuration loading does not inspect the embedding process's argv.

Requested reasoning is preserved across providers. Discovery admits a candidate only if the existing capability contract supports the request; unsupported controls are reported rather than silently removed. Catalogue admission is provisional: fresh provider-specific preflight and actual normalized-response checks remain required. No implicit fallback exists. Keys remain environment references, never persisted values.

All-local Gemma/Qwen is representable, not jointly resource-qualified. No new default or residency policy is introduced. The optional strict-free OpenRouter adapter is preserved and was not called in this correction.
