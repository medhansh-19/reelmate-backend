from __future__ import annotations

from app.pipeline import (
    AudioSignals,
    HookSignals,
    MediaMetadata,
    PipelineV1,
    TextOverlay,
    TextSignals,
    TimedSegment,
    build_scene_signals,
    no_audio_signals,
)
from app.scoring import (
    SubScores,
    aggregate_scores,
    score_av_sync,
    score_pipeline,
    score_text,
)


def _pipeline(*, good: bool, has_audio: bool = True) -> PipelineV1:
    duration = 30.0
    metadata = MediaMetadata(
        duration_seconds=duration,
        size_bytes=10_000_000,
        format_name="mov,mp4,m4a,3gp,3g2,mj2",
        video_codec="h264",
        width=1080,
        height=1920,
        frame_rate=30.0,
        rotation_degrees=0,
        has_audio=has_audio,
        audio_codec="aac" if has_audio else None,
        audio_sample_rate=48_000 if has_audio else None,
        audio_channels=2 if has_audio else None,
    )
    if good:
        scenes = build_scene_signals(duration, [float(value) for value in range(2, 30, 2)])
        overlays = [
            TextOverlay(
                text="Start here",
                timestamp_seconds=0.0,
                duration_seconds=2.0,
                position="top",
                confidence=92.0,
                flagged=False,
            ),
            TextOverlay(
                text="One clear takeaway",
                timestamp_seconds=8.0,
                duration_seconds=2.5,
                position="middle",
                confidence=88.0,
                flagged=False,
            ),
        ]
        text = TextSignals(
            overlays=overlays,
            frames_analyzed=20,
            frames_with_text=8,
            readable_overlay_ratio=1.0,
            has_text_in_hook=True,
        )
        hook = HookSignals(
            duration_analyzed_seconds=3.0,
            frames_analyzed=7,
            has_motion=True,
            motion_score=0.10,
            has_face=True,
            face_frame_ratio=0.75,
            has_text=True,
            cuts_in_hook=1,
        )
        audio = (
            AudioSignals(
                has_audio=True,
                bpm=120.0,
                rms_energy_mean=0.12,
                rms_energy_peak=0.40,
                energy="high",
                mood="intense",
                silence_gaps=[],
                silence_ratio=0.0,
            )
            if has_audio
            else no_audio_signals()
        )
    else:
        scenes = build_scene_signals(duration, [])
        overlays = [
            TextOverlay(
                text="blink",
                timestamp_seconds=5.0,
                duration_seconds=0.4,
                position="bottom",
                confidence=46.0,
                flagged=True,
            )
        ]
        text = TextSignals(
            overlays=overlays,
            frames_analyzed=20,
            frames_with_text=1,
            readable_overlay_ratio=0.0,
            has_text_in_hook=False,
        )
        hook = HookSignals(
            duration_analyzed_seconds=3.0,
            frames_analyzed=7,
            has_motion=False,
            motion_score=0.0,
            has_face=False,
            face_frame_ratio=0.0,
            has_text=False,
            cuts_in_hook=0,
        )
        audio = (
            AudioSignals(
                has_audio=True,
                bpm=120.0,
                rms_energy_mean=0.02,
                rms_energy_peak=0.04,
                energy="low",
                mood="intense",
                silence_gaps=[TimedSegment(start_seconds=5.0, duration_seconds=20.0)],
                silence_ratio=0.666667,
            )
            if has_audio
            else no_audio_signals()
        )

    return PipelineV1(
        metadata=metadata,
        scenes=scenes,
        audio=audio,
        text=text,
        hook=hook,
        representative_frame_timestamps_seconds=[
            0.0,
            0.5,
            1.0,
            1.5,
            2.0,
            2.5,
            3.0,
            10.0,
            20.0,
            29.95,
        ],
    )


def test_scoring_is_deterministic_and_versioned() -> None:
    pipeline = _pipeline(good=True)

    first = score_pipeline(pipeline)
    second = score_pipeline(pipeline)

    assert first.model_dump() == second.model_dump()
    assert first.score_version == "score-v1"
    assert first.score_label == "reel_readiness"
    assert first.score_experimental is True


def test_clear_good_signals_outscore_clear_bad_signals_by_20_points() -> None:
    good = score_pipeline(_pipeline(good=True))
    bad = score_pipeline(_pipeline(good=False))

    assert good.score - bad.score >= 20
    assert good.sub_scores.hook > bad.sub_scores.hook
    assert good.sub_scores.pacing > bad.sub_scores.pacing
    assert good.sub_scores.av_sync is not None
    assert bad.sub_scores.av_sync is not None
    assert good.sub_scores.av_sync > bad.sub_scores.av_sync


def test_no_audio_excludes_av_sync_and_renormalizes_aggregate() -> None:
    result = score_pipeline(_pipeline(good=True, has_audio=False))

    assert result.sub_scores.av_sync is None
    assert result.sub_scores.trend is None
    expected = aggregate_scores(
        SubScores(
            hook=result.sub_scores.hook,
            pacing=result.sub_scores.pacing,
            av_sync=None,
            text=result.sub_scores.text,
            trend=None,
        )
    )
    assert result.score == expected
    assert result.confidence < 1.0


def test_av_sync_distinguishes_on_beat_from_off_beat_cuts() -> None:
    scenes = build_scene_signals(8.0, [2.0, 4.0, 6.0])
    common = {
        "has_audio": True,
        "bpm": 60.0,
        "rms_energy_mean": 0.1,
        "rms_energy_peak": 0.2,
        "energy": "medium",
        "mood": "intense",
        "silence_gaps": [],
        "silence_ratio": 0.0,
    }
    on_beat = AudioSignals(**common, beat_timestamps_seconds=[0.0, 2.0, 4.0, 6.0])
    off_beat = AudioSignals(**common, beat_timestamps_seconds=[1.0, 3.0, 5.0, 7.0])

    on_score = score_av_sync(on_beat, scenes, duration_seconds=8.0)
    off_score = score_av_sync(off_beat, scenes, duration_seconds=8.0)

    assert on_score is not None and off_score is not None
    assert on_score - off_score >= 40


def test_trend_is_null_and_never_part_of_aggregate() -> None:
    scores = SubScores(hook=90, pacing=60, av_sync=None, text=30, trend=None)

    # (90*.30 + 60*.25 + 30*.10) / (.30 + .25 + .10) = 69.23
    assert aggregate_scores(scores) == 69
    assert scores.trend is None


def test_text_free_formats_receive_neutral_text_score() -> None:
    text = TextSignals(
        overlays=[],
        frames_analyzed=12,
        frames_with_text=0,
        readable_overlay_ratio=0.0,
        has_text_in_hook=False,
    )

    assert score_text(text) == 65


def test_all_score_outputs_stay_in_range() -> None:
    for candidate in (_pipeline(good=True), _pipeline(good=False)):
        result = score_pipeline(candidate)
        values = [
            result.score,
            result.sub_scores.hook,
            result.sub_scores.pacing,
            result.sub_scores.text,
        ]
        if result.sub_scores.av_sync is not None:
            values.append(result.sub_scores.av_sync)
        assert 5 <= result.score <= 95
        assert all(0 <= value <= 100 for value in values[1:])


def test_overall_score_never_hits_false_extremes() -> None:
    assert aggregate_scores(SubScores(hook=0, pacing=0, av_sync=0, text=0)) == 5
    assert aggregate_scores(SubScores(hook=100, pacing=100, av_sync=100, text=100)) == 95
