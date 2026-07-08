from dataclasses import dataclass, field


@dataclass
class MasonryContext:
    """Shared state for a single `_calculate_masonry_layout` execution."""

    source_model: object
    strategy: str
    strict_mode: bool
    column_width: int
    spacing: int
    viewport_width: int
    num_columns: int
    items_data: list = field(default_factory=list)
    page_size: int = 1000
    total_items: int = 0
    current_page: int = 0
    window_buffer: int = 0
    max_page: int = 0
    full_layout_mode: bool = False
    window_start_page: int = 0
    window_end_page: int = 0
    min_idx: int = 0
    max_idx: int = 0
    avg_h: float = 100.0
    avail_width: int = 0
    num_cols_est: int = 1
