from pathlib import Path

from scripts.compare_replay_corpus import (
    analyze_comparison,
    discover_capture_directories,
)
from scripts.replay_slow_inference import ReplayResult


def create_result(
    *,
    text: str,
    tokens: int,
    language: str = "en",
) -> ReplayResult:
    return ReplayResult(
        total_seconds=1.0,
        setup_seconds=0.2,
        decoding_seconds=0.8,
        language=language,
        confidence=0.9,
        output_segments=1,
        output_tokens=tokens,
        text=text,
    )


def test_discover_capture_directories_filters_by_name(
    tmp_path: Path,
) -> None:
    names = [
        "20260912T100000Z-old",
        "20260913T172655Z-first",
        "20260913T173000Z-middle",
        "20260913T173401Z-last",
    ]

    for name in names:
        directory = tmp_path / name
        directory.mkdir()
        (directory / "audio.npy").touch()
        (directory / "metadata.json").touch()

    result = discover_capture_directories(
        tmp_path,
        from_name="20260913T172655Z-first",
        to_name="20260913T173401Z-last",
    )

    assert [path.name for path in result] == names[1:]


def test_identical_result_is_not_suspicious() -> None:
    baseline = create_result(
        text="This is a normal transcription.",
        tokens=20,
    )

    candidate = create_result(
        text="This is a normal transcription.",
        tokens=20,
    )

    analysis = analyze_comparison(
        baseline=baseline,
        candidate=candidate,
        max_new_tokens=64,
    )

    assert analysis.similarity == 1.0
    assert analysis.suspicious_reasons == ()


def test_candidate_near_token_limit_is_flagged() -> None:
    analysis = analyze_comparison(
        baseline=create_result(
            text="A normal transcription.",
            tokens=70,
        ),
        candidate=create_result(
            text="A normal transcription.",
            tokens=62,
        ),
        max_new_tokens=64,
    )

    assert "candidate_near_token_limit" in (analysis.suspicious_reasons)


def test_much_shorter_candidate_is_flagged() -> None:
    analysis = analyze_comparison(
        baseline=create_result(
            text=("This is a reasonably long sentence that should not disappear."),
            tokens=30,
        ),
        candidate=create_result(
            text="This is short.",
            tokens=8,
        ),
        max_new_tokens=64,
    )

    assert "candidate_much_shorter" in (analysis.suspicious_reasons)
