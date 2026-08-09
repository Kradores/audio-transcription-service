## queue overflow should be observable
For example:
- audio.capture.started
- audio.capture.stopped
- audio.capture.device_selected
- audio.capture.device_changed
- audio.capture.recovery_started
- audio.capture.recovered
- audio.capture.frame_dropped
- audio.capture.error
Not yet decided, only on an idea level!

## audio pipeline events
### Important events:
capture_started
capture_stopped
capture_device_lost
capture_recovery_started
capture_recovered
audio_frame_dropped

speech_started
speech_ended
speech_segment_created

### Metrics such as:
capture_queue_depth
audio_frames_dropped
capture_recovery_count
speech_segment_duration
vad_processing_duration
normalization_processing_duration