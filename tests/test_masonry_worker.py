from taggui.widgets import masonry_worker
from taggui.widgets.masonry_worker import calculate_masonry_layout


def test_masonry_cache_lookup_does_not_create_directories(monkeypatch, tmp_path):
    monkeypatch.setattr(masonry_worker.Path, "home", lambda: tmp_path)

    read_path = masonry_worker._get_cache_path("read-only")
    assert not read_path.parent.exists()

    write_path = masonry_worker._get_cache_path("write", ensure_parent=True)
    assert write_path.parent.is_dir()


def test_masonry_layout_preserves_ties_sanitization_and_spacers():
    result = calculate_masonry_layout(
        [
            (0, 1.0),
            (1, 2.0),
            (2, 0.0),
            (999, ("SPACER", 30)),
            (3, 4.0),
        ],
        column_width=100,
        spacing=2,
        num_columns=2,
    )

    assert result == {
        "items": [
            {
                "index": 0,
                "x": 0,
                "y": 0,
                "width": 100,
                "height": 100,
                "aspect_ratio": 1.0,
            },
            {
                "index": 1,
                "x": 102,
                "y": 0,
                "width": 100,
                "height": 50,
                "aspect_ratio": 2.0,
            },
            {
                "index": 2,
                "x": 102,
                "y": 52,
                "width": 100,
                "height": 100,
                "aspect_ratio": 1.0,
            },
            {
                "index": -2,
                "x": 0,
                "y": 154,
                "width": 202,
                "height": 30,
                "aspect_ratio": 1.0,
            },
            {
                "index": 3,
                "x": 0,
                "y": 184,
                "width": 100,
                "height": 25,
                "aspect_ratio": 4.0,
            },
        ],
        "total_height": 211,
    }
