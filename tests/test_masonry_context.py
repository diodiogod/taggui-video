from taggui.widgets.image_list_masonry_context import MasonryContext


def test_masonry_context_defaults():
    ctx = MasonryContext(
        source_model=object(),
        strategy="full_compat",
        strict_mode=False,
        column_width=128,
        spacing=2,
        viewport_width=1024,
        num_columns=7,
    )

    assert ctx.items_data == []
    assert ctx.page_size == 1000
    assert ctx.total_items == 0
    assert ctx.avg_h == 100.0
    assert ctx.num_cols_est == 1
