# ADR-045: Per-Source Adaptive Language Selection for Multilingual Transcription

## Status

Accepted

## Date

2026-09-03

## Context

The service transcribes completed speech independently through a shared transcription executor.

Each transcription work item preserves its source:

```text
system_audio
microphone
```

but the underlying `Transcriber` intentionally operates on speech audio rather than source identity.

Until this decision, Faster-Whisper performed automatic language detection independently for each transcription work item.

Controlled microphone testing demonstrated that this behavior is unreliable for short multilingual speech.

### English baseline

Short English utterances between approximately 0.9 and 1.4 seconds were generally transcribed correctly, although detected-language probability varied substantially.

### Romanian automatic-detection baseline

Equivalent Romanian testing produced unstable language selection on short inputs.

Observed detections included:

```text
ru
cs
it
hr
bg
en
```

for speech that was intentionally Romanian.

Incorrect language selection materially affected decoding and produced Cyrillic output, unrelated-language text, nonsense, or empty results.

Longer Romanian inputs of approximately four to six seconds were substantially more reliable and were generally detected as Romanian with high probability.

### Model-size experiment

The behavior was reproduced with:

```text
small
medium
large-v3
```

Increasing model size improved some longer-sentence transcription quality but did not eliminate short-fragment language ambiguity.

Therefore model size alone is not the primary solution.

### Explicit-language experiment

When Faster-Whisper was explicitly supplied:

```text
language="ro"
```

short Romanian inputs that had previously been unstable were transcribed correctly, including phrases around one second long.

This establishes that:

```text
captured audio
+
Whisper decoding
```

are capable of producing good results when the appropriate language context is known.

The primary failure is therefore the loss of conversational language context between independent transcription work items.

### Multilingual requirement

A permanently fixed language is insufficient.

A real conversation may switch between languages, and the two captured sources may use different languages.

For example:

```text
microphone      → Romanian
system_audio    → English
```

or one participant may switch from Romanian to English during the conversation.

Language context must therefore be stable without becoming permanently fixed.

### Concurrency interaction

ADR-042 allows several transcription workers to process work concurrently.

Adaptive language selection introduces mutable temporal state.

Two work items from the same source must not concurrently modify that state or observe it out of chronological order.

Cross-source concurrency remains desirable.

---

## Decision

### 1. Introduce source-aware adaptive language orchestration outside the concrete transcriber

Language-state ownership will not be added to `FasterWhisperTranscriber`.

The low-level transcriber remains independent of:

```text
system_audio
microphone
```

A source-aware transcription-processing component will receive the existing:

```text
TranscriptionWorkItem
    source
    segment
```

and coordinate language selection before invoking the underlying `Transcriber`.

Conceptually:

```text
TranscriptionWorkItem
        ↓
source-aware transcription processor
        ├── per-source language state
        └── language-selection policy
        ↓
Transcriber
        ↓
Faster-Whisper
```

This preserves the existing source-agnostic transcription implementation boundary.

### 2. Extend the transcription boundary with an optional language selection

The application-level transcription operation will support:

```text
language = None
```

for automatic language detection and:

```text
language = "<language code>"
```

for explicit-language decoding.

Conceptually:

```python
transcribe(
    segment: SpeechSegment,
    *,
    language: str | None = None,
) -> TranscriptionResult
```

This remains application-owned and does not expose Faster-Whisper-specific types.

### 3. Support explicit language-policy modes

Language behavior will be configuration-driven.

The application will support:

```text
auto
fixed
adaptive
```

`auto` preserves independent per-work-item language detection.

`fixed` always uses one configured language.

`adaptive` maintains conversational language state independently for each source.

Configuration validation will make invalid mode combinations impossible where practical.

### 4. Adaptive state is per source

Adaptive mode maintains independent state for:

```text
system_audio
microphone
```

One source must never change the established language of the other source.

Each source state contains conceptually:

```text
established language
candidate switch language
candidate confirmation count
```

No process-global conversation language is introduced.

### 5. Short work items cannot independently change language state

Short speech is linguistically ambiguous.

A transcription work item shorter than the configured probe duration is not eligible to establish or switch source language.

When an established language exists, such a work item is decoded explicitly using that language.

For example:

```text
established = ro

0.9 s "Da."
        ↓
language="ro"
        ↓
"Da."
```

Short work items therefore benefit from previously established conversational context.

### 6. Unknown sources bootstrap through automatic detection

A source initially has no established language unless an optional initial adaptive language was configured.

While the language is unknown, work items are transcribed with automatic language detection.

Short inputs may be transcribed but cannot establish source state.

Only a probe-eligible input with sufficient detection probability may establish the initial source language.

This prevents a short ambiguous fragment from permanently establishing an incorrect language.

### 7. Informative work items act as language probes

A work item at or above the configured minimum probe duration is eligible to test whether the source language has changed.

The probe is performed by normal automatic transcription:

```text
transcribe(language=None)
```

The resulting transcript, detected language, and language probability are available from the same model invocation.

A separate full transcription call is not required for a successful probe.

### 8. Same-language probes preserve the established language

If an eligible probe detects the currently established language, the automatic result is accepted.

Any pending competing candidate is cleared.

The established language remains unchanged.

### 9. Strong competing-language probes create switch candidates

If an eligible probe detects a different language with probability at or above the configured switch threshold:

```text
established = ro
detected = en
probability >= threshold
```

the detected language becomes a switch candidate.

The automatically decoded result for that work item is accepted in the detected language.

A candidate does not immediately replace the established source language unless the configured confirmation requirement has been satisfied.

### 10. Language switching uses hysteresis

A competing language must receive the configured number of strong confirmations before it replaces the established language.

For example:

```text
established = ro

probe 1:
    en 0.96
    candidate=en
    confirmations=1

probe 2:
    en 0.97
    confirmations=2

        ↓

established = en
candidate cleared
```

This prevents one-off quotations or erroneous language detections from immediately changing the source language.

The confirmation count remains configuration-driven.

### 11. A candidate does not control short speech before confirmation

While a competing language is still only a candidate, short work items continue using the currently established language.

This is intentionally conservative.

It avoids a single foreign-language quotation causing subsequent short speech to be decoded in the candidate language.

A genuine switch may therefore require one or more informative turns before all subsequent short speech uses the new language.

The number of confirmations may be reduced through configuration if runtime evidence favors faster switching.

### 12. Competing evidence cancels or replaces candidates

A strong probe matching the established language clears a pending candidate.

A strong probe identifying another competing language replaces the previous candidate and starts its confirmation count again.

Language state must not oscillate on low-confidence evidence.

### 13. Low-confidence conflicting probes fall back to the established language

If an eligible automatic probe produces a different language but its probability is below the configured switch threshold, it is not considered credible evidence of a switch.

The automatic result is discarded and the same work item is transcribed explicitly using the established language.

This is the exceptional path that may require a second transcription invocation.

For example:

```text
established = ro

automatic probe:
    hr 0.20

        ↓

reject language decision

        ↓

transcribe(language="ro")
```

This favors transcription stability over accepting a low-confidence unrelated language.

### 14. Language confidence semantics must remain truthful

`TranscriptionResult.language` represents the language actually used for the accepted transcription result.

For automatic language detection:

```text
confidence = detected-language probability
```

For explicitly selected language:

```text
confidence = None
```

The application must not treat Faster-Whisper's internally reported probability of `1.0` for an explicitly supplied language as independent language-detection confidence.

If a low-confidence automatic probe is discarded and explicitly retranscribed using the established language, the persisted result has:

```text
language = established language
confidence = None
```

Rejected probe metadata remains available through observability rather than being represented as confidence for the accepted transcript.

### 15. Adaptive language state is conversation-scoped

Language state begins fresh for a new conversation/application processing lifecycle.

Normal capture recovery or device replacement does not reset language state.

A capture discontinuity resets stateful audio-processing components according to ADR-035, but it does not imply that the participant changed spoken language.

Language context therefore survives source-device recovery within the same conversation.

### 16. Same-source adaptive processing is serialized

When adaptive mode is active, at most one language-state-mutating transcription operation for a source may be in progress at a time.

The order must follow accepted work-item order for that source.

This guarantees that:

```text
microphone item N
```

updates language state before:

```text
microphone item N+1
```

makes its language decision.

The same rule applies independently to system audio.

### 17. Cross-source transcription may remain concurrent

Per-source serialization does not require global serialization.

Conceptually:

```text
microphone N ──────────────► worker A
                               │
                               ▼
                         microphone state

system_audio M ────────────► worker B
                               │
                               ▼
                         system state
```

The two sources may execute concurrently because their language states are independent.

This preserves the principal throughput benefit of ADR-042 for the normal two-source application.

The exact synchronization mechanism is an implementation detail as long as per-source ordering is deterministic.

### 18. Adaptive thresholds are configuration, not architectural constants

Initial experimental configuration may resemble:

```yaml
transcription:
  language:
    mode: adaptive
    initial_language: null
    min_probe_duration_seconds: 3.0
    switch_probability_threshold: 0.85
    switch_confirmations: 2
```

These numerical values are initial runtime-validation values.

They must be tuned from measured multilingual conversations rather than treated as permanent constants.

### 19. Language selection must be observable

At minimum, diagnostics must make visible:

```text
source
segment start
segment duration
established language
selected language
whether a probe occurred
detected language
detection probability
candidate language
candidate confirmation count
decision reason
confirmed language switches
fallback retranscriptions
```

Logs must clearly distinguish:

```text
auto-detected language
```

from:

```text
state-selected / configured language
```

so that explicit language selection is never misinterpreted as 100% detection confidence.

---

## Resulting architecture

```text
system SpeechPipeline
        ↓
system aggregator
        ↓
TranscriptionWorkItem
        │
        ├──────────────────────────────┐
        │                              │
        ▼                              │
                                    shared
microphone SpeechPipeline           bounded
        ↓                           executor
microphone aggregator                 │
        ↓                              │
TranscriptionWorkItem ────────────────┘
                                       │
                          source-aware processing
                                       │
                       ┌───────────────┴───────────────┐
                       ▼                               ▼
                system language state          microphone language state
                       │                               │
                       └───────────────┬───────────────┘
                                       ▼
                                  Transcriber
                                       │
                            language=None / explicit
                                       │
                                       ▼
                                Faster-Whisper
                                       │
                                       ▼
                            TranscriptionResult
                                       │
                                       ▼
                                  persistence
```

---

## Consequences

### Positive

- Short speech benefits from established conversational language context.
- Genuine language changes remain supported.
- System audio and microphone retain independent language behavior.
- A one-off foreign-language turn can be transcribed correctly without immediately changing persistent state.
- Low-confidence unrelated language detections no longer automatically control decoding.
- Increasing Whisper model size is not required as the primary solution to short-fragment language instability.
- The concrete Faster-Whisper adapter remains independent of audio-source identity.
- Language policy is independently testable with fake transcription implementations.
- Existing aggregation and speech-segmentation responsibilities remain unchanged.
- Configuration can trade switching responsiveness against stability.
- Cross-source transcription concurrency remains possible.

### Negative

- Adaptive transcription introduces mutable per-source state.
- Short speech before the initial language is established still relies on independent automatic detection.
- A genuine language change may require multiple informative segments before it becomes established.
- Short speech occurring between candidate detection and confirmation may still be decoded using the previous established language.
- Low-confidence conflicting probes may require a second transcription invocation.
- Per-source ordering can reduce effective concurrency for workloads dominated by a single source.
- Intra-utterance code-switching inside one speech segment is not fully solved by this policy.
- More observability and state-machine tests are required.

---

## Alternatives Considered

### Automatically detect language for every work item

Rejected as the default adaptive policy.

Controlled testing demonstrated that short Romanian fragments can be assigned unrelated languages even when the speech is otherwise suitable for Whisper transcription.

### Permanently configure one language

Rejected as the general solution.

It substantially improves same-language short transcription but prevents genuine multilingual switching.

### Increase the Whisper model size

Rejected as the primary solution.

`small`, `medium`, and `large-v3` all reproduced the fundamental ambiguity of independently detecting language from short Romanian speech.

### Force aggregation to produce only long transcription inputs

Rejected as the primary solution.

It would increase latency, combine more semantic speech turns, and make transcription batching responsible for compensating for language-state loss.

### Allow one strong different-language result to always switch immediately

Rejected as the default.

A single foreign-language quotation or erroneous detection should not permanently change the source language.

The confirmation requirement remains configurable and may be set to one where faster switching is preferred.

### Let candidate language immediately control all subsequent short speech

Rejected initially.

This makes a single unconfirmed candidate capable of biasing unrelated following fragments.

The established language remains authoritative until the candidate is confirmed.

### Store one global conversation language

Rejected.

System audio and microphone can legitimately speak different languages.

Language state must therefore remain source-local.

### Put language state directly inside `FasterWhisperTranscriber`

Rejected.

Source identity and conversational history are application concerns, while the concrete transcriber should remain a source-agnostic adapter around the replaceable STT engine.

### Run a separate language-detection model for every probe

Deferred.

The existing automatic transcription call already provides the detected language and probability while producing a usable transcript.

A separate detector would introduce additional model execution and another replaceable component without demonstrated need.

A dedicated or accumulated language detector may be reconsidered if runtime evidence shows that switches consisting only of short utterances cannot be handled adequately by probe-eligible transcription inputs.

---

## Testing Requirements

Unit tests must cover:

```text
unknown-language bootstrap
short input not establishing state
initial high-confidence establishment
explicit decoding of short established-language speech
same-language probes
candidate creation
candidate confirmation
confirmed switching
candidate cancellation
candidate replacement
low-confidence fallback retranscription
independent state per source
conversation-state reset
capture discontinuity preserving language state
auto mode
fixed mode
explicit-language confidence semantics
per-source execution serialization
cross-source concurrency
graceful executor shutdown with adaptive state
```

Real-runtime acceptance must include at least:

```text
Romanian → English → Romanian
```

with both short and probe-eligible utterances around each language transition.

Validation must inspect:

```text
transcript correctness
detected-language probability
selected language
switch timing
candidate behavior
fallback count
executor queue pressure
transcription duration
capture frame drops
executor rejection/failure
```

The adaptive policy is considered validated only when it improves multilingual short-fragment stability without destabilizing the previously accepted real-time capture and transcription-execution architecture.

---

## Related Decisions

- ADR-030 — Transcription Boundary and Faster-Whisper Adapter
- ADR-035 — Audio Capture Discontinuity Propagation and Processing State Reset
- ADR-036 — Decouple Real-Time Audio Processing from Transcription Execution
- ADR-037 — Runtime Transcription Overload and Segment Rejection Policy
- ADR-039 — Multi-Source System and Microphone Audio Processing Architecture
- ADR-041 — Per-Source Speech Segment Aggregation Before Transcription Execution
- ADR-042 — Concurrent Transcription Execution with Multiple Whisper Workers
- ADR-044 — AMD GPU Transcription Runtime and CPU Fallback Strategy