"""Training-model video constraints shared by the UI and editing tools."""

from dataclasses import dataclass

from utils.settings import settings


VIDEO_TRAINING_PROFILE_SETTING = 'video_training_profile'
DEFAULT_VIDEO_TRAINING_PROFILE = 'wan'


@dataclass(frozen=True)
class VideoTrainingProfile:
    key: str
    display_name: str
    frame_step: int
    frame_offset: int
    recommended_fps: float

    @property
    def frame_rule(self) -> str:
        return f'{self.frame_step}n+{self.frame_offset}'

    def is_valid_frame_count(self, frame_count: int) -> bool:
        return (
            frame_count >= self.frame_offset
            and (frame_count - self.frame_offset) % self.frame_step == 0
        )

    def nearest_valid_frame_count(self, frame_count: int) -> int:
        """Return the closest positive count matching this profile's frame rule."""
        frame_count = max(1, int(frame_count))
        minimum = max(1, self.frame_offset)
        if frame_count <= minimum:
            return minimum

        lower_n = max(0, (frame_count - self.frame_offset) // self.frame_step)
        lower = lower_n * self.frame_step + self.frame_offset
        upper = (lower_n + 1) * self.frame_step + self.frame_offset
        if lower < minimum:
            return upper
        return lower if frame_count - lower <= upper - frame_count else upper


VIDEO_TRAINING_PROFILES = {
    'wan': VideoTrainingProfile('wan', 'WAN', 4, 1, 16.0),
    'h3_minimax': VideoTrainingProfile('h3_minimax', 'H3 MinMax', 17, 5, 24.0),
}


def normalize_video_training_profile(value) -> str:
    key = str(value or '').strip().lower()
    return key if key in VIDEO_TRAINING_PROFILES else DEFAULT_VIDEO_TRAINING_PROFILE


def get_video_training_profile(value=None) -> VideoTrainingProfile:
    if value is None:
        value = settings.value(
            VIDEO_TRAINING_PROFILE_SETTING,
            defaultValue=DEFAULT_VIDEO_TRAINING_PROFILE,
            type=str,
        )
    return VIDEO_TRAINING_PROFILES[normalize_video_training_profile(value)]
