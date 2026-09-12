# ADR-048: Bounded Lifetime for Adaptive Language Candidate Evidence

## Status

Accepted

## Date

2026-09-11

## Context

ADR-045 introduced per-source adaptive language state, and ADR-047 refined that design so that low-confidence automatic language evidence does not mutate persistent language state or trigger a second explicit Whisper transcription.

Runtime validation of ADR-047 confirmed the intended improvements:

- unknown-language bootstrap now requires repeated strong evidence;
- low-confidence probes preserve their automatic transcription result;
- low-confidence evidence does not clear or replace candidates;
- duplicate fallback transcription was eliminated.

However, a realistic long-running multilingual test exposed a new weakness.

Adaptive language candidates currently have no lifetime. Once a strong probe creates a candidate, that candidate remains indefinitely until one of the following occurs:

- another strong probe confirms it;
- strong evidence for another language replaces it;
- strong evidence for the established language clears it.

Weak evidence intentionally does not mutate candidate state under ADR-047.

During runtime validation, continuous Russian `system_audio` produced a false high-confidence Belarusian detection:

```text
be 0.872
→ candidate=be/1
```

The following probes did not provide strong enough evidence to mutate the candidate, so the Belarusian candidate remained active.

Approximately 53 seconds later another false Belarusian detection occurred:

```text
be 0.934
```

Because the previous candidate was still active, the second detection counted as confirmation and caused:

```text
ru → be
```

even though the underlying system audio had remained Russian.

This demonstrates that confirmation count alone is insufficient. Strong observations separated by a long period should not necessarily be treated as corroborating evidence for the same language transition.

## Decision

Adaptive language candidates will have a bounded evidence lifetime.

A new adaptive-language configuration value will be introduced:

```yaml
transcription:
  language:
    mode: adaptive
    candidate_max_gap_seconds: 30.0
```

`candidate_max_gap_seconds` defines the maximum allowed source-audio timeline gap between consecutive strong observations that may contribute to the same candidate confirmation sequence.

The value will initially default to:

```text
30.0 seconds
```

This is an experimental configuration value derived from current runtime evidence and may be tuned after further validation.

Candidate timing will use the source audio timeline represented by `SpeechSegment.timestamp` and `SpeechSegment.duration`.

It will not use wall-clock time, executor processing time, queue wait, or transcription completion time.

For each candidate, adaptive state will retain the end time of the most recent strong evidence:

```text
candidate_last_strong_evidence_end
```

When a strong probe matching the existing candidate arrives, the processor will calculate:

```text
gap =
    current_segment.timestamp
    - candidate_last_strong_evidence_end
```

Negative values caused by overlap will be treated as zero.

If:

```text
gap <= candidate_max_gap_seconds
```

the evidence belongs to the current candidate sequence and increments its confirmation count.

If:

```text
gap > candidate_max_gap_seconds
```

the previous candidate evidence is considered stale.

The current strong observation starts a new candidate sequence:

```text
candidate_language = detected_language
candidate_confirmations = 1
candidate_last_strong_evidence_end = current_segment_end
```

It does not confirm the expired candidate.

A strong observation for a different competing language continues to replace the current candidate immediately and resets the candidate evidence timestamp.

Strong evidence matching the established language continues to clear the candidate immediately.

Low-confidence probes continue to follow ADR-047:

```text
no candidate creation
no candidate confirmation
no candidate replacement
no candidate clearing
no candidate timestamp refresh
```

Short segments decoded explicitly using the established language do not refresh candidate evidence.

Candidate lifetime is evaluated lazily when probe evidence is processed. No timer, background task, or periodic cleanup mechanism will be introduced.

The same candidate lifetime rule applies to:

```text
unknown-language bootstrap
and
established-language switching
```

Each audio source continues to maintain independent conversation-scoped adaptive language state.

## State

`AdaptiveLanguageState` will retain:

```text
established_language
candidate_language
candidate_confirmations
candidate_last_strong_evidence_end
```

Whenever candidate state is cleared, all candidate-related state must be cleared together:

```text
candidate_language = None
candidate_confirmations = 0
candidate_last_strong_evidence_end = None
```

Whenever a candidate is created or replaced:

```text
candidate_language = detected_language
candidate_confirmations = 1
candidate_last_strong_evidence_end = current_segment_end
```

Whenever valid strong evidence confirms the existing candidate:

```text
candidate_confirmations += 1
candidate_last_strong_evidence_end = current_segment_end
```

## Consequences

The primary benefit is that unrelated high-confidence false detections separated by a long portion of a conversation can no longer accumulate into a language switch.

ADR-047's evidence-preservation rule remains intact: weak evidence cannot destroy a legitimate pending candidate.

Language transition evidence must now be both sufficiently confident and sufficiently temporally related.

The design remains deterministic, per-source, configuration-driven, and independent of executor performance.

A legitimate language transition whose strong evidence occurs only at widely separated intervals may take longer to establish.

The appropriate maximum gap may differ across workloads, which is why the value remains configurable.

No additional threads, timers, clocks, or background state-management components are introduced.

## Alternatives Considered

### Keep candidates indefinitely

Rejected because the runtime validation demonstrated a false `ru → be` transition caused by strong false detections separated by approximately 53 seconds.

### Let low-confidence evidence clear stale candidates

Rejected because this would reintroduce the evidence-destruction problem solved by ADR-047.

### Refresh candidate lifetime on low-confidence matching evidence

Rejected because evidence below `switch_probability_threshold` is intentionally insufficient to mutate persistent state. Allowing it to extend candidate lifetime would violate that invariant.

### Use wall-clock time

Rejected because executor backlog and slow inference would then alter language semantics. Candidate lifetime must depend on the captured conversation timeline, not machine performance.

### Add a background expiry timer

Rejected because expiry only matters when new language evidence is processed. Lazy evaluation is simpler, deterministic, and requires no additional lifecycle management.

## Testing Requirements

Unit tests must verify:

- strong matching candidate evidence inside the configured gap increments confirmation;
- strong matching candidate evidence beyond the configured gap starts again at confirmation `1`;
- candidate replacement resets the evidence timestamp;
- strong established-language evidence clears candidate language, confirmations, and evidence timestamp;
- low-confidence evidence does not refresh candidate lifetime;
- short explicitly decoded segments do not refresh candidate lifetime;
- bootstrap candidates follow the same expiry rule;
- candidate lifetime is independent per source;
- overlapping source timestamps do not produce a negative semantic gap;
- queue delay and wall-clock delay are irrelevant to candidate lifetime.

Runtime validation must repeat a realistic long-running two-source workload and verify that temporally distant false detections cannot combine into an incorrect state transition.

## Supersedes

ADR-048 does not replace ADR-047.

It extends ADR-047 by bounding the temporal lifetime of strong candidate evidence.

## Related Decisions

- ADR-030 — Transcription Boundary and Faster-Whisper Adapter
- ADR-036 — Decouple Real-Time Audio Processing from Transcription Execution
- ADR-039 — Multi-Source System and Microphone Audio Processing Architecture
- ADR-041 — Per-Source Speech Segment Aggregation Before Transcription Execution
- ADR-042 — Concurrent Transcription Execution with Multiple Whisper Workers
- ADR-044 — AMD GPU Transcription Runtime and CPU Fallback Strategy
- ADR-045 — Per-Source Adaptive Language Selection for Multilingual Transcription
- ADR-046 — Configurable Microphone Gain at the Transcription Boundary
- ADR-047 — Evidence-Preserving Adaptive Language State Transitions