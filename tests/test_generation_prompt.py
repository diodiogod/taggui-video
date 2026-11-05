import json
from pathlib import Path
import sys

import pytest
from PIL import Image, PngImagePlugin

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'taggui'))
from utils.generation_prompt import read_generation_prompts


def write_png(path, **metadata):
    info = PngImagePlugin.PngInfo()
    for key, value in metadata.items():
        info.add_text(key, json.dumps(value) if isinstance(value, dict) else value)
    Image.new('RGB', (4, 4), 'red').save(path, pnginfo=info)


def node(kind, **inputs):
    return {'class_type': kind, 'inputs': inputs}


def simple_graph(positive='a {red|blue} bird # note', negative='blur'):
    return {
        '1': node('SimplePromptStandalone', positive=positive, negative=negative),
        '2': node('CLIPTextEncode', text=['1', 0], clip=['9', 0]),
        '3': node('CLIPTextEncode', text=['1', 1], clip=['9', 0]),
        '4': node('KSampler', positive=['2', 0], negative=['3', 0]),
        '5': node('SimplePromptStandalone', positive='unused text', negative='unused negative'),
    }


@pytest.mark.parametrize('kind', ['SimplePromptStandalone', 'PgPromptSimple'])
def test_simple_prompt_follows_positive_connection_and_preserves_original(tmp_path, kind):
    path = tmp_path / 'image.png'
    graph = simple_graph()
    graph['1']['class_type'] = kind
    write_png(path, prompt=graph)
    before = path.read_bytes()
    found = read_generation_prompts(path)
    assert [item.text for item in found] == ['a {red|blue} bird # note']
    assert 'Original Simple Prompt input' in found[0].note
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


def test_positive_and_negative_clip_nodes_do_not_get_confused(tmp_path):
    path = tmp_path / 'image.png'
    write_png(path, prompt={
        '1': node('CLIPTextEncode', text='bad, blurry'),
        '2': node('CLIPTextEncode', text='bright landscape'),
        '3': node('KSampler', positive=['2', 0], negative=['1', 0]),
    })
    assert [item.text for item in read_generation_prompts(path)] == ['bright landscape']


def test_actual_saved_positive_takes_priority_over_original_node(tmp_path):
    path = tmp_path / 'image.png'
    write_png(path, prompt=simple_graph(), PositivePrompt_17='a red bird')
    assert [item.text for item in read_generation_prompts(path)] == ['a red bird']


def test_saved_positive_json_string_is_decoded_as_comfyui_writes_it(tmp_path):
    path = tmp_path / 'image.png'
    write_png(path, prompt=simple_graph(), PositivePrompt_17=json.dumps('a red bird\nwith "wings"'))
    assert [item.text for item in read_generation_prompts(path)] == ['a red bird\nwith "wings"']


@pytest.mark.parametrize('field', ['positive_prompt', 'Positive Prompt', 'positive', 'umi_prompt'])
def test_explicit_prompt_fields_take_priority_over_embedded_workflow(tmp_path, field):
    path = tmp_path / 'image.png'
    write_png(path, prompt=simple_graph(), **{field: 'saved positive'})
    assert [item.text for item in read_generation_prompts(path)] == ['saved positive']


def test_explicit_positive_is_read_without_parsing_embedded_workflow(tmp_path, monkeypatch):
    from utils import generation_prompt

    path = tmp_path / 'image.png'
    write_png(path, prompt=simple_graph(), positive_prompt='saved positive')
    parse_object = generation_prompt._json_object
    def reject_workflow_parse(value):
        if isinstance(value, str) and 'SimplePromptStandalone' in value:
            raise AssertionError('Explicit positive metadata should be read first')
        return parse_object(value)
    monkeypatch.setattr(generation_prompt, '_json_object', reject_workflow_parse)
    assert [item.text for item in read_generation_prompts(path)] == ['saved positive']


def test_invokeai_metadata_takes_priority_over_comfyui_workflow(tmp_path):
    path = tmp_path / 'image.png'
    write_png(path, prompt=simple_graph(), invokeai_metadata={
        'positive_prompt': 'invoke prompt', 'negative_prompt': 'invoke negative'})
    assert [item.text for item in read_generation_prompts(path)] == ['invoke prompt']


def test_fooocus_comment_takes_priority_over_comfyui_workflow(tmp_path):
    path = tmp_path / 'image.png'
    write_png(path, prompt=simple_graph(), Comment={
        'prompt': 'fooocus prompt', 'negative_prompt': 'fooocus negative'})
    assert [item.text for item in read_generation_prompts(path)] == ['fooocus prompt']


def test_fooocus_jpeg_comment_reads_utf8_bytes(tmp_path):
    path = tmp_path / 'image.jpg'
    comment = json.dumps({'prompt': 'fooocus café', 'negative_prompt': 'blur'},
                         ensure_ascii=False).encode('utf-8')
    Image.new('RGB', (4, 4), 'blue').save(path, comment=comment)
    assert [item.text for item in read_generation_prompts(path)] == ['fooocus café']


def test_plain_prompt_metadata_is_not_assumed_to_be_a_comfyui_graph(tmp_path):
    path = tmp_path / 'image.png'
    write_png(path, prompt='saved text', negative_prompt='bad',
              workflow={'nodes': [{'id': 1, 'type': 'SimplePromptStandalone',
                                    'widgets_values': ['different', 'bad']}]})
    assert [item.text for item in read_generation_prompts(path)] == ['saved text']


def test_plain_positive_metadata_preserves_intentional_quotes(tmp_path):
    path = tmp_path / 'image.png'
    write_png(path, positive_prompt='"a quoted subject"', prompt=simple_graph())
    assert [item.text for item in read_generation_prompts(path)] == ['"a quoted subject"']


def test_json_exif_explicit_positive_has_priority_over_workflow(tmp_path):
    path = tmp_path / 'image.webp'
    exif = Image.Exif()
    payload = {'positive_prompt': 'saved in exif', 'negative_prompt': 'blur',
               'prompt': simple_graph()}
    exif[0x8769] = {0x9286: b'UNICODE\x00' + json.dumps(payload).encode('utf-16-be')}
    Image.new('RGB', (4, 4), 'blue').save(path, exif=exif)
    assert [item.text for item in read_generation_prompts(path)] == ['saved in exif']


def test_comfy_webp_named_positive_exif_takes_priority_over_graph(tmp_path):
    path = tmp_path / 'image.webp'
    exif = Image.Exif()
    exif[0x0110] = 'prompt:' + json.dumps(simple_graph())
    exif[0x010F] = 'workflow:' + json.dumps({'nodes': []})
    exif[0x010E] = 'other:' + json.dumps('not prompt metadata')
    exif[0x010D] = 'positive_prompt:' + json.dumps('saved result')
    Image.new('RGB', (4, 4), 'blue').save(path, exif=exif)
    assert [item.text for item in read_generation_prompts(path)] == ['saved result']


def test_swarm_json_parameters_returns_prompt_not_the_serialized_object(tmp_path):
    path = tmp_path / 'image.png'
    write_png(path, prompt=simple_graph(), parameters={
        'sui_image_params': {'prompt': 'swarm prompt', 'negativeprompt': 'blur'}})
    assert [item.text for item in read_generation_prompts(path)] == ['swarm prompt']


def test_unknown_json_parameters_falls_back_to_workflow(tmp_path):
    path = tmp_path / 'image.png'
    write_png(path, prompt=simple_graph(), parameters={'unrecognized': 'not prompt text'})
    assert [item.text for item in read_generation_prompts(path)] == ['a {red|blue} bird # note']


def test_conflicting_saved_prompts_are_offered_as_choices(tmp_path):
    path = tmp_path / 'image.png'
    write_png(path, prompt=simple_graph(), PositivePrompt_17='first saved prompt',
              parameters='second saved prompt\nNegative prompt: bad\nSteps: 20')
    assert {item.text for item in read_generation_prompts(path)} == {
        'first saved prompt', 'second saved prompt'}


def test_sdxl_and_multiple_samplers_return_distinct_choices(tmp_path):
    path = tmp_path / 'image.png'
    graph = {
        '1': node('CLIPTextEncodeSDXL', text_g='global prompt', text_l='local prompt'),
        '2': node('CFGGuider', positive=['1', 0], negative=['9', 0]),
        '3': node('CLIPTextEncode', text='another prompt'),
        '4': node('KSampler', positive=['3', 0], negative=['9', 0]),
        '5': node('KSampler', positive=['3', 0], negative=['9', 0]),
    }
    write_png(path, prompt=graph)
    assert [item.text for item in read_generation_prompts(path)] == [
        'global prompt', 'local prompt', 'another prompt']


@pytest.mark.parametrize('index', [1, ['8', 0]])
def test_easy_index_switch_follows_selected_branch(tmp_path, index):
    path = tmp_path / 'image.png'
    graph = simple_graph(positive='right branch')
    graph['6'] = node('easy anythingIndexSwitch', index=index,
                      value0=['5', 0], value1=['1', 0])
    graph['8'] = node('easy int', value=1)
    graph['2']['inputs']['text'] = ['6', 0]
    write_png(path, prompt=graph)
    result = read_generation_prompts(path)
    assert [item.text for item in result] == ['right branch']
    assert result[0].verified


def test_unknown_switch_index_shows_possible_branches_without_auto_copy(tmp_path):
    path = tmp_path / 'image.png'
    graph = simple_graph(positive='first branch')
    graph['6'] = node('easy anythingIndexSwitch', index=['7', 0],
                      value0=['5', 0], value1=['1', 0])
    graph['7'] = node('UnknownIntegerSource')
    graph['2']['inputs']['text'] = ['6', 0]
    write_png(path, prompt=graph)
    result = read_generation_prompts(path)
    assert {item.text for item in result} == {'first branch', 'unused text'}
    assert all(not item.verified and 'switch branch' in item.note for item in result)


def test_unrelated_positive_negative_reader_is_not_a_sampling_anchor(tmp_path):
    path = tmp_path / 'image.png'
    graph = {
        '1': node('SDPromptReader', positive='unrelated', negative='bad'),
        '2': node('CLIPTextEncode', text='actual'),
        '3': node('KSampler', positive=['2', 0], negative=['5', 0]),
    }
    write_png(path, prompt=graph)
    assert [item.text for item in read_generation_prompts(path)] == ['actual']


def test_unreadable_positive_branch_prevents_automatic_copy(tmp_path):
    path = tmp_path / 'image.png'
    graph = {
        '1': node('CLIPTextEncode', text='one candidate'),
        '2': node('KSampler', positive=['1', 0]),
        '3': node('KSampler', positive=['4', 0]),
        '4': node('UnsupportedPromptNode', opaque_input='unknown'),
    }
    write_png(path, prompt=graph)
    result = read_generation_prompts(path)
    assert [item.text for item in result] == ['one candidate']
    assert not result[0].verified
    assert 'could not be read' in result[0].note


def test_dual_text_encoder_does_not_treat_negative_output_as_positive(tmp_path):
    path = tmp_path / 'image.png'
    graph = {
        '1': node('TextEncodeFibo2', prompt='positive', negative_prompt='negative'),
        '2': node('KSampler', positive=['1', 1], negative=['1', 0]),
    }
    write_png(path, prompt=graph)
    assert read_generation_prompts(path) == []


def test_fibo_dual_encoder_follows_simple_prompt_positive_output(tmp_path):
    path = tmp_path / 'image.png'
    graph = {
        '1': node('SimplePromptStandalone', positive='real prompt', negative='negative text'),
        '2': node('TextEncodeFibo2', prompt=['1', 0], negative_prompt=['1', 1]),
        '3': node('KSampler', positive=['2', 0], negative=['2', 1]),
    }
    write_png(path, prompt=graph)
    assert [item.text for item in read_generation_prompts(path)] == ['real prompt']


@pytest.mark.parametrize('suffix', ['.webp', '.jpg'])
def test_comfy_exif_graph_in_webp_and_jpeg(tmp_path, suffix):
    path = tmp_path / f'image{suffix}'
    exif = Image.Exif()
    exif[0x010F] = 'Prompt:' + json.dumps(simple_graph(positive='from exif'))
    Image.new('RGB', (4, 4), 'blue').save(path, exif=exif)
    assert [item.text for item in read_generation_prompts(path)] == ['from exif']


@pytest.mark.parametrize('encoding', ['utf-16-be', 'utf-16-le', 'utf-16'])
def test_unicode_exif_user_comment_with_a1111_parameters(tmp_path, encoding):
    path = tmp_path / 'image.webp'
    exif = Image.Exif()
    content = 'café by the sea\nNegative prompt: blurry\nSteps: 25, CFG scale: 5'
    exif[0x8769] = {0x9286: b'UNICODE\x00' + content.encode(encoding)}
    Image.new('RGB', (4, 4), 'blue').save(path, exif=exif)
    assert [item.text for item in read_generation_prompts(path)] == ['café by the sea']


def test_exif_parameters_detect_negative_marker_case_insensitively(tmp_path):
    path = tmp_path / 'image.webp'
    exif = Image.Exif()
    content = 'positive text\nnegative prompt: blurry'
    exif[0x8769] = {0x9286: b'UNICODE\x00' + content.encode('utf-16-be')}
    Image.new('RGB', (4, 4), 'blue').save(path, exif=exif)
    assert [item.text for item in read_generation_prompts(path)] == ['positive text']


def test_a1111_parameters_preserve_lora_and_exclude_negative(tmp_path):
    path = tmp_path / 'image.png'
    write_png(path, parameters='a castle <lora:castle:1>\nNegative prompt: ugly\nSteps: 20, CFG: 5')
    assert [item.text for item in read_generation_prompts(path)] == ['a castle <lora:castle:1>']


def test_workflow_sidecar_uses_links_and_skips_inactive_nodes(tmp_path):
    path = tmp_path / 'image.png'
    write_png(path)
    workflow = {
        'version': 1, 'state': {},
        'nodes': [
            {'id': 1, 'type': 'SimplePromptStandalone', 'mode': 0,
             'widgets_values': ['sidecar positive', 'sidecar negative'], 'inputs': []},
            {'id': 2, 'type': 'CLIPTextEncode', 'inputs': [{'name': 'text'}],
             'widgets_values': ['']},
            {'id': 3, 'type': 'KSampler', 'inputs': [{'name': 'positive'}, {'name': 'negative'}]},
            {'id': 4, 'type': 'SimplePromptStandalone', 'mode': 4,
             'widgets_values': ['bypassed positive', 'bypassed negative']},
        ],
        'links': [[1, 1, 0, 2, 0, 'STRING'], [2, 2, 0, 3, 0, 'CONDITIONING']],
    }
    sidecar = path.with_suffix('.json')
    sidecar.write_text(json.dumps(workflow), encoding='utf-8')
    original = sidecar.read_bytes()
    assert [item.text for item in read_generation_prompts(path)] == ['sidecar positive']
    assert sidecar.read_bytes() == original


def test_unconnected_simple_prompt_is_marked_unverified(tmp_path):
    path = tmp_path / 'image.png'
    write_png(path, prompt={'1': node('SimplePromptStandalone', positive='maybe', negative='no')})
    result = read_generation_prompts(path)
    assert result[0].text == 'maybe'
    assert 'could not be verified' in result[0].note


def test_graph_cycles_and_negative_output_do_not_yield_false_prompts(tmp_path):
    path = tmp_path / 'image.png'
    write_png(path, prompt={
        '1': node('CLIPTextEncode', text=['2', 0]),
        '2': node('Reroute', value=['1', 0]),
        '3': node('KSampler', positive=['1', 0], negative=['4', 0]),
    })
    assert read_generation_prompts(path) == []
    graph = simple_graph()
    graph['2']['inputs']['text'] = ['1', 1]
    del graph['5']
    write_png(path, prompt=graph)
    # A Simple Prompt node is still discoverable as an explicitly unverified fallback.
    assert 'could not be verified' in read_generation_prompts(path)[0].note


def test_foreign_or_taggui_sidecar_is_not_mistaken_for_a_prompt(tmp_path):
    path = tmp_path / 'image.png'
    write_png(path)
    sidecar = path.with_suffix('.json')
    sidecar.write_text('{"version": 1, "crop": [1, 2, 3, 4]}', encoding='utf-8')
    assert read_generation_prompts(path) == []
    sidecar.write_text('{"version": 1, "crop": [1, 2, 3, 4], "parameters": "not a workflow"}',
                       encoding='utf-8')
    assert read_generation_prompts(path) == []
    sidecar.write_text('{broken', encoding='utf-8')
    assert read_generation_prompts(path) == []
