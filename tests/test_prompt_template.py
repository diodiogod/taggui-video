from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'taggui'))

from auto_captioning.prompt_template import replace_template_variables
from utils.image import Image


def test_conditional_tag_block_is_only_included_for_tagged_images(tmp_path):
    template = (
        'Folder: {folder}. '
        '##IF{tags} THEN##Use these tags: {tags}.##ENDIF##'
    )
    tagged = Image(tmp_path / 'images' / 'sample.png', (100, 100), ['cat', 'blue'])
    untagged = Image(tmp_path / 'images' / 'empty.png', (100, 100), [])

    assert replace_template_variables(template, tagged, False) == (
        'Folder: images. Use these tags: cat, blue.'
    )
    assert replace_template_variables(template, untagged, False) == (
        'Folder: images. '
    )


def test_conditional_else_and_trailing_form(tmp_path):
    tagged = Image(tmp_path / 'tagged.png', (100, 100), ['cat'])
    untagged = Image(tmp_path / 'empty.png', (100, 100), [])

    block = '##IF{tags}##has tags##ELSE##has no tags##ENDIF##'
    assert replace_template_variables(block, tagged, False) == 'has tags'
    assert replace_template_variables(block, untagged, False) == 'has no tags'

    trailing = 'Start. ##IF{tags} then##Existing: {tags}'
    assert replace_template_variables(trailing, tagged, False) == (
        'Start. Existing: cat'
    )
    assert replace_template_variables(trailing, untagged, False) == 'Start. '


def test_skip_hash_affects_tag_condition(tmp_path):
    image = Image(tmp_path / 'hash.png', (100, 100), ['#character'])
    template = 'Before ##IF{tags}##Tags: {tags}##ENDIF##'

    assert replace_template_variables(template, image, False) == (
        'Before Tags: #character'
    )
    assert replace_template_variables(template, image, True) == 'Before '
