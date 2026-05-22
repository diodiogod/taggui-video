from PySide6.QtCore import QSettings, Signal
from PySide6.QtGui import QColor

# Defaults for settings that are accessed from multiple places.
DEFAULT_SETTINGS = {
    'font_size': 16,
    # Common image formats that are supported in PySide6, as well as JPEG XL and video formats.
    'image_list_file_formats': 'bmp, gif, jpg, jpeg, jxl, png, tif, tiff, webp, mp4, avi, mov, mkv, webm',
    'repair_extensionless_images': False,
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
    'image_list_title_strip_height': 8,  # Compact image-list dock title strip height in px
    'floating_viewer_wall_gap_px': 6,  # Shared gap between floating windows and screen edges for masonry layouts
    'floating_viewer_wall_alignment': 'Top center',
    'floating_viewer_rearrange_preserve_screen_order': True,
    'floating_double_click_detail_zoom_percent': 400,  # 400% => 4x fallback zoom on floating double-click detail jump
    'floating_resize_preserve_aspect_by_default': False,
    'image_list_double_click_action': 'spawn viewer',  # spawn viewer, system default app
    'compare_fit_mode': 'preserve',  # preserve, fill, stretch (image compare overlay mode)
    'video_compare_fit_mode': 'preserve',  # preserve, fill, stretch (video compare window mode)
    'video_compare_audio_mode': 'ambient_mix',  # dominant, ambient_mix
    'video_multi_compare_experimental': True,  # Allow adding 3rd/4th video layers in compare window
    'video_playback_backend': 'mpv_experimental',  # qt_hybrid, mpv_experimental, vlc_experimental
    'video_muted': True,
    'video_volume': 1.0,
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
    'thumbnail_show_review_badges': True,
    'thumbnail_show_reaction_badges': True,
    'thumbnail_show_star_rating_badge': True,
    'thumbnail_reaction_badge_position': 'Left',
    'thumbnail_star_rating_badge_position': 'Right',
    'thumbnail_star_rating_badge_style': 'Gold Chip: ★3',
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

THUMBNAIL_BADGE_SIDE_LEFT = 'left'
THUMBNAIL_BADGE_SIDE_RIGHT = 'right'
THUMBNAIL_BADGE_SIDES = (
    THUMBNAIL_BADGE_SIDE_LEFT,
    THUMBNAIL_BADGE_SIDE_RIGHT,
)

THUMBNAIL_STAR_BADGE_STYLE_OPTIONS = (
    ('gold_chip_star_left', 'Gold Chip: ★3'),
    ('gold_chip_star_right', 'Gold Chip: 3★'),
    ('review_tile_star_left', 'Review Tile: ★3'),
    ('review_tile_star_right', 'Review Tile: 3★'),
    ('dark_chip_star_left', 'Dark Chip: ★3'),
    ('dark_chip_star_right', 'Dark Chip: 3★'),
    ('outline_chip_star_left', 'Outline Chip: ★3'),
    ('outline_chip_star_right', 'Outline Chip: 3★'),
    ('sunset_chip_star_left', 'Sunset Chip: ★3'),
    ('sunset_chip_star_right', 'Sunset Chip: 3★'),
    ('glass_pill_star_left', 'Glass Pill: ★3'),
    ('glass_pill_star_right', 'Glass Pill: 3★'),
    ('split_capsule_star_left', 'Split Capsule: ★3'),
    ('split_capsule_star_right', 'Split Capsule: 3★'),
    ('halo_tag_star_left', 'Halo Tag: ★3'),
    ('halo_tag_star_right', 'Halo Tag: 3★'),
)
THUMBNAIL_STAR_BADGE_STYLE_LABEL_TO_KEY = {
    label.strip().casefold(): key
    for key, label in THUMBNAIL_STAR_BADGE_STYLE_OPTIONS
}
THUMBNAIL_STAR_BADGE_STYLE_KEYS = tuple(
    key for key, _label in THUMBNAIL_STAR_BADGE_STYLE_OPTIONS
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


def normalize_thumbnail_badge_side(value) -> str:
    text = str(value or '').strip().lower()
    if text in THUMBNAIL_BADGE_SIDES:
        return text
    return THUMBNAIL_BADGE_SIDE_LEFT


def normalize_thumbnail_star_badge_style(value) -> str:
    text = str(value or '').strip()
    lowered = text.casefold()
    if lowered in THUMBNAIL_STAR_BADGE_STYLE_LABEL_TO_KEY:
        return THUMBNAIL_STAR_BADGE_STYLE_LABEL_TO_KEY[lowered]
    if lowered in THUMBNAIL_STAR_BADGE_STYLE_KEYS:
        return lowered
    return 'gold_chip_star_left'


def get_thumbnail_star_badge_style_spec(style_key: str | None = None) -> dict:
    normalized = normalize_thumbnail_star_badge_style(style_key)
    specs = {
        'gold_chip_star_left': {
            'variant': 'pill',
            'label_order': 'star_left',
            'fill': QColor(255, 233, 166, 245),
            'text': QColor(122, 82, 0, 255),
            'outline': QColor(255, 255, 255, 235),
            'shadow': QColor(0, 0, 0, 60),
            'radius': 5.0,
            'font_size': 9.0,
            'padding_x': 12,
        },
        'gold_chip_star_right': {
            'variant': 'pill',
            'label_order': 'star_right',
            'fill': QColor(255, 233, 166, 245),
            'text': QColor(122, 82, 0, 255),
            'outline': QColor(255, 255, 255, 235),
            'shadow': QColor(0, 0, 0, 60),
            'radius': 5.0,
            'font_size': 9.0,
            'padding_x': 12,
        },
        'review_tile_star_left': {
            'variant': 'pill',
            'label_order': 'star_left',
            'fill': QColor(255, 193, 7, 238),
            'text': QColor(255, 255, 255, 248),
            'outline': QColor(255, 255, 255, 235),
            'shadow': QColor(0, 0, 0, 60),
            'radius': 4.0,
            'font_size': 8.6,
            'padding_x': 10,
        },
        'review_tile_star_right': {
            'variant': 'pill',
            'label_order': 'star_right',
            'fill': QColor(255, 193, 7, 238),
            'text': QColor(255, 255, 255, 248),
            'outline': QColor(255, 255, 255, 235),
            'shadow': QColor(0, 0, 0, 60),
            'radius': 4.0,
            'font_size': 8.6,
            'padding_x': 10,
        },
        'dark_chip_star_left': {
            'variant': 'pill',
            'label_order': 'star_left',
            'fill': QColor(34, 36, 42, 240),
            'text': QColor(255, 199, 99, 255),
            'outline': QColor(255, 255, 255, 205),
            'shadow': QColor(0, 0, 0, 68),
            'radius': 5.0,
            'font_size': 9.0,
            'padding_x': 12,
        },
        'dark_chip_star_right': {
            'variant': 'pill',
            'label_order': 'star_right',
            'fill': QColor(34, 36, 42, 240),
            'text': QColor(255, 199, 99, 255),
            'outline': QColor(255, 255, 255, 205),
            'shadow': QColor(0, 0, 0, 68),
            'radius': 5.0,
            'font_size': 9.0,
            'padding_x': 12,
        },
        'outline_chip_star_left': {
            'variant': 'pill',
            'label_order': 'star_left',
            'fill': QColor(255, 249, 223, 108),
            'text': QColor(176, 122, 0, 255),
            'outline': QColor(240, 198, 73, 255),
            'shadow': QColor(0, 0, 0, 52),
            'radius': 5.0,
            'font_size': 8.8,
            'padding_x': 12,
        },
        'outline_chip_star_right': {
            'variant': 'pill',
            'label_order': 'star_right',
            'fill': QColor(255, 249, 223, 108),
            'text': QColor(176, 122, 0, 255),
            'outline': QColor(240, 198, 73, 255),
            'shadow': QColor(0, 0, 0, 52),
            'radius': 5.0,
            'font_size': 8.8,
            'padding_x': 12,
        },
        'sunset_chip_star_left': {
            'variant': 'pill',
            'label_order': 'star_left',
            'fill': QColor(255, 173, 96, 242),
            'text': QColor(91, 33, 3, 255),
            'outline': QColor(255, 244, 235, 230),
            'shadow': QColor(0, 0, 0, 60),
            'radius': 6.0,
            'font_size': 9.0,
            'padding_x': 12,
        },
        'sunset_chip_star_right': {
            'variant': 'pill',
            'label_order': 'star_right',
            'fill': QColor(255, 173, 96, 242),
            'text': QColor(91, 33, 3, 255),
            'outline': QColor(255, 244, 235, 230),
            'shadow': QColor(0, 0, 0, 60),
            'radius': 6.0,
            'font_size': 9.0,
            'padding_x': 12,
        },
        'glass_pill_star_left': {
            'variant': 'glass',
            'label_order': 'star_left',
            'fill': QColor(255, 252, 243, 112),
            'text': QColor(255, 247, 230, 255),
            'outline': QColor(255, 255, 255, 165),
            'shadow': QColor(0, 0, 0, 38),
            'radius': 4.5,
            'font_size': 8.8,
            'padding_x': 14,
            'glass_highlight': QColor(255, 255, 255, 68),
        },
        'glass_pill_star_right': {
            'variant': 'glass',
            'label_order': 'star_right',
            'fill': QColor(255, 252, 243, 112),
            'text': QColor(255, 247, 230, 255),
            'outline': QColor(255, 255, 255, 165),
            'shadow': QColor(0, 0, 0, 38),
            'radius': 4.5,
            'font_size': 8.8,
            'padding_x': 14,
            'glass_highlight': QColor(255, 255, 255, 68),
        },
        'split_capsule_star_left': {
            'variant': 'split',
            'label_order': 'star_left',
            'fill': QColor(255, 244, 217, 228),
            'text': QColor(92, 54, 0, 255),
            'outline': QColor(255, 255, 255, 220),
            'shadow': QColor(0, 0, 0, 54),
            'radius': 7.0,
            'font_size': 8.8,
            'padding_x': 16,
            'accent_fill': QColor(245, 185, 54, 246),
            'accent_text': QColor(255, 255, 255, 255),
            'accent_width': 20,
            'divider': QColor(172, 115, 0, 70),
        },
        'split_capsule_star_right': {
            'variant': 'split',
            'label_order': 'star_right',
            'fill': QColor(255, 244, 217, 228),
            'text': QColor(92, 54, 0, 255),
            'outline': QColor(255, 255, 255, 220),
            'shadow': QColor(0, 0, 0, 54),
            'radius': 7.0,
            'font_size': 8.8,
            'padding_x': 16,
            'accent_fill': QColor(245, 185, 54, 246),
            'accent_text': QColor(255, 255, 255, 255),
            'accent_width': 20,
            'divider': QColor(172, 115, 0, 70),
        },
        'halo_tag_star_left': {
            'variant': 'halo',
            'label_order': 'star_left',
            'fill': QColor(40, 34, 26, 176),
            'text': QColor(255, 240, 199, 255),
            'outline': QColor(255, 214, 124, 170),
            'shadow': QColor(0, 0, 0, 60),
            'radius': 7.0,
            'font_size': 8.8,
            'padding_x': 12,
            'halo_fill': QColor(255, 210, 94, 245),
            'halo_text': QColor(92, 42, 0, 255),
            'halo_diameter': 17,
        },
        'halo_tag_star_right': {
            'variant': 'halo',
            'label_order': 'star_right',
            'fill': QColor(40, 34, 26, 176),
            'text': QColor(255, 240, 199, 255),
            'outline': QColor(255, 214, 124, 170),
            'shadow': QColor(0, 0, 0, 60),
            'radius': 7.0,
            'font_size': 8.8,
            'padding_x': 12,
            'halo_fill': QColor(255, 210, 94, 245),
            'halo_text': QColor(92, 42, 0, 255),
            'halo_diameter': 17,
        },
    }
    return specs.get(normalized, specs['gold_chip_star_left'])


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
