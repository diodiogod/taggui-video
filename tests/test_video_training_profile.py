from utils.video.training_profile import VIDEO_TRAINING_PROFILES


def test_wan_frame_rule_and_nearest_counts():
    profile = VIDEO_TRAINING_PROFILES['wan']

    assert profile.is_valid_frame_count(81)
    assert not profile.is_valid_frame_count(80)
    assert profile.nearest_valid_frame_count(80) == 81
    assert profile.recommended_fps == 16.0


def test_h3_minimax_frame_rule_and_documented_lengths():
    profile = VIDEO_TRAINING_PROFILES['h3_minimax']

    for frame_count in (39, 56, 73, 90, 124):
        assert profile.is_valid_frame_count(frame_count)
    assert not profile.is_valid_frame_count(81)
    assert profile.nearest_valid_frame_count(80) == 73
    assert profile.recommended_fps == 24.0
