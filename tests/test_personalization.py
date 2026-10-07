from app.personalization import derive_profile


def test_recurring_issue_requires_three_distinct_analyses() -> None:
    history = [
        {
            "result": {
                "pipeline": {"energy": "high", "avg_clip_length": 1.2},
                "feedback": [
                    {"type": "hook", "issue_code": "slow_hook"},
                    {"type": "hook", "issue_code": "slow_hook"},
                ],
            }
        },
        {
            "result": {
                "pipeline": {"energy": "high", "avg_clip_length": 1.4},
                "feedback": [{"type": "hook", "issue_code": "slow_hook"}],
            }
        },
    ]

    profile = derive_profile(history)

    assert profile.recurring_issue_codes == []
    assert profile.editing_style == "fast-cut"
    assert profile.typical_energy == "high"


def test_recurring_issue_is_added_after_three_analyses() -> None:
    history = [
        {"result": {"feedback": [{"type": "pacing", "issue_code": "long_clips"}]}},
        {"result": {"feedback": [{"type": "pacing", "issue_code": "long_clips"}]}},
        {"result": {"feedback": [{"type": "pacing", "issue_code": "long_clips"}]}},
    ]

    assert derive_profile(history).recurring_issue_codes == ["long_clips"]


def test_passive_profile_infers_niche_style_and_confidence() -> None:
    history = [
        {
            "result": {
                "pipeline_summary": {
                    "niche": "fitness",
                    "audio": {"energy": "high"},
                    "scenes": {"average_clip_length_seconds": 2.8},
                    "hook": {"has_face": True},
                }
            }
        },
        {
            "result": {
                "pipeline_summary": {
                    "niche": "fitness",
                    "audio": {"energy": "medium"},
                    "scenes": {"average_clip_length_seconds": 2.2},
                    "hook": {"has_face": True},
                }
            }
        },
    ]

    profile = derive_profile(history)

    assert profile.inferred_niche == "fitness"
    assert profile.niche_confidence == 1.0
    assert profile.editing_style == "talking-head"
    assert profile.editing_style_confidence == 1.0
    assert profile.typical_energy_confidence == 0.5
