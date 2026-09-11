## ADR-047: Evidence-Preserving Adaptive Language State Transitions

## Status
Accepted

## Context

ADR-045 introduced independent per-source adaptive language state to stabilize short multilingual transcription. It established explicit decoding for short speech, automatic probe transcription for longer speech, candidate confirmation for language switching, and explicit retranscription in the established language when a conflicting automatic probe had insufficient confidence.

Realistic multilingual runtime validation with simultaneous Russian system audio and Romanian/English microphone speech exposed three limitations.

First, unknown-language bootstrap establishes a language after one high-confidence probe. A Romanian microphone utterance was incorrectly detected as Russian with probability `0.902`, causing Russian to become established and biasing subsequent microphone transcription.

Second, low-confidence conflicting probes currently clear any pending candidate and are retranscribed using the established language. Repeated English microphone utterances were correctly identified as English but commonly with probabilities below `0.85`; these results were discarded and explicitly retranscribed as Romanian, degrading transcript quality.

Third, fallback retranscription substantially increased Whisper work. During the realistic run the executor remained lossless, but queue wait reached `19.550 s` and transcription duration reached `19.771 s`.

## Decision

Adaptive language processing will separate **accepted transcript selection** from **persistent language-state mutation**.

For probe-eligible segments, the automatic Whisper transcription result will be the accepted result regardless of whether its language probability is sufficient to mutate adaptive state.

Low-confidence automatic probes will not cause a second explicit retranscription.

Only evidence meeting `switch_probability_threshold` may create, confirm, replace, or clear a language candidate.

Low-confidence evidence will not mutate candidate state.

A strong probe matching the established language will clear a competing candidate.

A strong probe matching the current candidate will increment its confirmation count.

A strong probe identifying a different competing language will replace the current candidate and begin confirmation for the new language.

Unknown-language bootstrap will use the same candidate-confirmation mechanism as established-language switching. A single high-confidence probe will no longer establish language immediately.

`switch_confirmations` will initially control both bootstrap establishment and subsequent switching.

Short segments below `min_probe_duration_seconds` will continue to use the established language explicitly once a language is established.

Per-source state isolation, conversation-scoped state lifetime, and same-source serialization from ADR-045 remain unchanged.

## Consequences

Positive consequences are fewer false initial establishments, preservation of useful automatic multilingual transcripts, candidate state that cannot be erased by weak evidence, substantially fewer Whisper invocations, lower queue pressure, and simpler separation between transcription output and state confidence.

The main negative consequence is that an individual low-confidence automatic probe may still produce an incorrect transcript. However, that uncertain result cannot corrupt persistent language state, and subsequent short speech remains protected by the established language.

Language switching may still be slow if the configured threshold is higher than the probabilities produced by a particular speaker/microphone/language combination. Threshold tuning remains configuration-driven and should occur after this state-machine change is validated.

## Alternatives considered

Keeping low-confidence fallback is rejected because this run shows both transcript degradation and significant extra inference cost.

Lowering only the switch threshold is deferred because high-confidence false detections (`ru 0.902`, `pt 0.956`) demonstrate that threshold reduction alone does not solve false state transitions.

Adding a dedicated language detector remains deferred because the current Whisper evidence is sufficient to evaluate a simpler state-machine correction first.

Adding another transcription worker is deferred because unnecessary duplicate fallback inference should be removed before changing execution capacity.

## Testing requirements

Unit tests should add coverage for: confirmation-based unknown bootstrap; low-confidence evidence preserving an existing candidate; low-confidence same-candidate evidence not incrementing or clearing the candidate; low-confidence third-language evidence not replacing the candidate; strong established-language evidence clearing a candidate; and confirmation that low-confidence probes invoke Whisper only once.

The real-runtime acceptance should repeat the exact useful workload we just discovered: continuous Russian `system_audio` plus microphone Romanian → English → Romanian, including short utterances around transitions.

Acceptance should verify transcript quality, candidate transitions, established-language transitions, number of Whisper invocations, queue wait, maximum transcription latency, frame drops, rejected jobs, and failures.

## Supersedes

ADR-047 would supersede ADR-045's rules for:

```text
unknown-language immediate establishment
low-confidence candidate clearing
low-confidence explicit fallback retranscription
```

All other ADR-045 decisions remain accepted.

## Related decisions
ADR-030, ADR-036, ADR-039, ADR-041, ADR-042, ADR-044, ADR-045, ADR-046.