from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'taggui'))

from utils.caption_annotations import merge_caption_entries_with_disk_tags


def test_new_disk_tags_precede_workspace_that_is_fully_excluded():
    stored = [
        {'text': 'old first', 'needs_review': False, 'excluded': True},
        {'text': 'old second', 'needs_review': True, 'excluded': True},
    ]

    merged = merge_caption_entries_with_disk_tags(stored, ['generated'])

    assert [entry['text'] for entry in merged] == [
        'generated', 'old first', 'old second',
    ]
    assert merged[0]['excluded'] is False
    assert merged[1]['excluded'] is True
    assert merged[2]['excluded'] is True
    assert merged[2]['needs_review'] is True


def test_disk_tags_keep_existing_classified_order_when_some_are_included():
    stored = [
        {'text': 'first', 'needs_review': False, 'excluded': False},
        {'text': 'old excluded', 'needs_review': False, 'excluded': True},
        {'text': 'last', 'needs_review': True, 'excluded': False},
    ]

    merged = merge_caption_entries_with_disk_tags(
        stored,
        ['generated', 'first', 'last'],
    )

    assert [entry['text'] for entry in merged] == [
        'generated', 'first', 'old excluded', 'last',
    ]
    assert merged[0]['excluded'] is False
    assert merged[2]['excluded'] is True
    assert merged[3]['needs_review'] is True
