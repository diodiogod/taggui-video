from PySide6.QtCore import QSettings, Signal

# Defaults for settings that are accessed from multiple places.
DEFAULT_SETTINGS = {
    'font_size': 16,
    # Common image formats that are supported in PySide6, as well as JPEG XL and video formats.
    'image_list_file_formats': 'bmp, gif, jpg, jpeg, jxl, png, tif, tiff, webp, mp4, avi, mov, mkv, webm',
    'image_list_image_width': 120,
    'tag_separator': ',',
    'insert_space_after_tag_separator': True,
    'autocomplete_tags': True,
    'models_directory_path': '',
    'marking_models_directory_path': '',
    'export_filter': 'All images',
    'export_preset': 'SDXL, SD3, Flux',
    'export_resolution': 1024,
    'export_bucket_res_size': 64,
    'export_latent_size': 8,
    'export_quantize_alpha': True,
    'export_masking_strategy': 'remove',
    'export_masked_content': 'blur + noise',
    'export_preferred_sizes' : '1024:1024, 1408:704, 1216:832, 1152:896, 1344:768, 1536:640',
    'export_upscaling': False,
    'export_bucket_strategy': 'crop',
    'trainer_target_resolution': 1024,
    'export_format': '.png - PNG',
    'export_quality': 100,
    'export_color_space': 'sRGB',
    'export_caption_algorithm': 'tag list (using tag separator)',
    'export_separate_newline': 'Create additional line',
    'export_directory_path': '',
    'export_keep_dir_structure': False,
    'export_filter_hashtag': True,
    'spell_check_enabled': True,
    'grammar_check_mode': 'free_api',
    'speed_slider_theme_index': 12,  # Forest Light
    'recent_directories': [],
    'image_list_filter_history': [],
    # Cache settings
    'enable_dimension_cache': True,
    'enable_thumbnail_cache': True,
    'thumbnail_cache_location': '',  # Empty = default (~/.taggui_cache/thumbnails)
    'thumbnail_eviction_pages': 3,  # How many pages to keep loaded on each side (1-5, higher = more VRAM but smoother)
    'max_pages_in_memory': 20,  # Max paginated pages held in RAM (higher = smoother revisits, higher RAM)
    'pagination_threshold': 0,  # Minimum images to enable pagination mode (0 = always paginate, higher = only for large datasets)
    'image_list_sort_dir': 'ASC',
    'image_list_random_seed': 0,
    'image_list_random_seed_history': [],
    'diagnostic_log_mode': 'essential',  # off, essential, verbose
    'masonry_list_switch_threshold': 150,  # Auto-switch to ListMode when thumbnail size reaches this px
    'floating_double_click_detail_zoom_percent': 400,  # 400% => 4x fallback zoom on floating double-click detail jump
    'image_list_double_click_action': 'spawn viewer',  # spawn viewer, system default app
    'compare_fit_mode': 'preserve',  # preserve, fill, stretch (image compare overlay mode)
    'video_compare_fit_mode': 'preserve',  # preserve, fill, stretch (video compare window mode)
    'video_compare_audio_mode': 'ambient_mix',  # dominant, ambient_mix
    'video_multi_compare_experimental': True,  # Allow adding 3rd/4th video layers in compare window
    'video_playback_backend': 'mpv_experimental',  # qt_hybrid, mpv_experimental, vlc_experimental
    'auto_marking_merge_overlaps': False,
    'auto_marking_merge_overlap_threshold': 0.6,
    'disable_thinking': True,
    # GPU preferences
    'video_playback_gpu_preference': 'system_default',  # system_default, high_performance, power_saving
    'video_ffmpeg_accel_mode': 'none',  # none, cuda
    'video_ffmpeg_cuda_device': 0,
    'video_controls_visibility_mode': 'auto',  # always, auto, off (main viewer)
    'auto_captioner_layout_mode': 'compact',  # compact, classic
    'review_badge_schema': '',
    'review_badge_text_color': '#FFFFFF',
    'review_badge_font_size': 9,
    'review_badge_corner_radius': 5,
}


class Settings(QSettings):
    # Signal that shows that the setting with the given string was changes
    change = Signal(str, object, name='settingsChanged')

    def __init__(self):
        super().__init__('taggui', 'taggui')

    def setValue(self, key, value):
        super().setValue(key, value)
        self.change.emit(key, value)

# Common shared instance to ensure the Signal is also shared
settings = Settings()

VIDEO_CONTROLS_VISIBILITY_ALWAYS = 'always'
VIDEO_CONTROLS_VISIBILITY_AUTO = 'auto'
VIDEO_CONTROLS_VISIBILITY_OFF = 'off'
VIDEO_CONTROLS_VISIBILITY_MODES = (
    VIDEO_CONTROLS_VISIBILITY_ALWAYS,
    VIDEO_CONTROLS_VISIBILITY_AUTO,
    VIDEO_CONTROLS_VISIBILITY_OFF,
)

AUTO_CAPTIONER_LAYOUT_MODE_COMPACT = 'compact'
AUTO_CAPTIONER_LAYOUT_MODE_CLASSIC = 'classic'
AUTO_CAPTIONER_LAYOUT_MODES = (
    AUTO_CAPTIONER_LAYOUT_MODE_COMPACT,
    AUTO_CAPTIONER_LAYOUT_MODE_CLASSIC,
)


def normalize_video_controls_visibility_mode(value) -> str:
    if isinstance(value, bool):
        return (
            VIDEO_CONTROLS_VISIBILITY_ALWAYS
            if value
            else VIDEO_CONTROLS_VISIBILITY_AUTO
        )
    text = str(value or '').strip().lower()
    if text in VIDEO_CONTROLS_VISIBILITY_MODES:
        return text
    return VIDEO_CONTROLS_VISIBILITY_AUTO


def load_video_controls_visibility_mode() -> str:
    raw_mode = settings.value('video_controls_visibility_mode', defaultValue='', type=str)
    mode = normalize_video_controls_visibility_mode(raw_mode)
    if str(raw_mode or '').strip():
        return mode
    legacy_always_show = settings.value('video_always_show_controls', False, type=bool)
    return normalize_video_controls_visibility_mode(bool(legacy_always_show))


def persist_video_controls_visibility_mode(mode: str):
    normalized = normalize_video_controls_visibility_mode(mode)
    settings.setValue('video_controls_visibility_mode', normalized)
    settings.setValue(
        'video_always_show_controls',
        normalized == VIDEO_CONTROLS_VISIBILITY_ALWAYS,
    )


def normalize_auto_captioner_layout_mode(value) -> str:
    text = str(value or '').strip().lower()
    if text in AUTO_CAPTIONER_LAYOUT_MODES:
        return text
    return AUTO_CAPTIONER_LAYOUT_MODE_COMPACT


def load_auto_captioner_layout_mode() -> str:
    raw_mode = settings.value(
        'auto_captioner_layout_mode',
        defaultValue=DEFAULT_SETTINGS['auto_captioner_layout_mode'],
        type=str,
    )
    return normalize_auto_captioner_layout_mode(raw_mode)


def persist_auto_captioner_layout_mode(mode: str):
    settings.setValue(
        'auto_captioner_layout_mode',
        normalize_auto_captioner_layout_mode(mode),
    )


def get_tag_separator() -> str:
    tag_separator = settings.value(
        'tag_separator', defaultValue=DEFAULT_SETTINGS['tag_separator'],
        type=str)
    insert_space_after_tag_separator = settings.value(
        'insert_space_after_tag_separator',
        defaultValue=DEFAULT_SETTINGS['insert_space_after_tag_separator'],
        type=bool)
    if insert_space_after_tag_separator:
        tag_separator += ' '
    return tag_separator
