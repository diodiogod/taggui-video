from utils.video.training_profile import VIDEO_TRAINING_PROFILES
from controllers.video_editing_controller import VideoEditingController


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


def test_h3_adjacent_valid_counts_are_strict():
    profile = VIDEO_TRAINING_PROFILES['h3_minimax']

    assert profile.previous_valid_frame_count(130) == 124
    assert profile.next_valid_frame_count(130) == 141
    assert profile.previous_valid_frame_count(124) == 107
    assert profile.next_valid_frame_count(124) == 141


def test_compatible_speed_lands_on_requested_output_count():
    speed = VideoEditingController._profile_compatible_speed(
        input_frames=169,
        input_fps=30.0,
        target_fps=30.0,
        target_frames=124,
    )

    output_frames = round((169 / 30.0) / speed * 30.0)
    assert output_frames == 124
