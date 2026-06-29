import json

import pytest

from taggui.utils.pipeline import (
    PipelineDefinition,
    PipelineStep,
    PipelineStore,
    PipelineValidationError,
    default_pipeline,
    parse_auto_mark_class_specs,
)


def test_pipeline_store_round_trip(tmp_path):
    store = PipelineStore(tmp_path / "pipelines.json")
    pipeline = default_pipeline("Character details")
    pipeline.steps[0].settings = {"model": "face.pt", "confidence": 0.4}

    store.save([pipeline])
    restored = store.load()

    assert len(restored) == 1
    assert restored[0].to_dict() == pipeline.to_dict()


def test_pipeline_store_writes_versioned_json(tmp_path):
    store = PipelineStore(tmp_path / "pipelines.json")
    store.save([PipelineDefinition("One", [PipelineStep("save")])])

    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["pipelines"][0]["steps"][0]["type"] == "save"


def test_pipeline_rejects_unknown_step_type():
    pipeline = PipelineDefinition("Broken", [PipelineStep("shell_command")])
    with pytest.raises(PipelineValidationError, match="Unsupported pipeline step"):
        pipeline.validate()


def test_pipeline_rejects_duplicate_step_ids():
    step = PipelineStep("save")
    pipeline = PipelineDefinition(
        "Broken",
        [step, PipelineStep("save", id=step.id)],
    )
    with pytest.raises(PipelineValidationError, match="Duplicate pipeline step ID"):
        pipeline.validate()


def test_pipeline_rejects_non_object_step_settings():
    with pytest.raises(PipelineValidationError, match="settings must be an object"):
        PipelineStep.from_dict({"type": "save", "settings": ["invalid"]})


def test_auto_mark_class_specs_support_label_overrides():
    class_names, overrides = parse_auto_mark_class_specs(
        "eye{person eye}, hand, TOOL{held tool}"
    )

    assert class_names == ["eye", "hand", "TOOL"]
    assert overrides == {"eye": "person eye", "tool": "held tool"}


def test_auto_mark_class_specs_accept_saved_list_values_and_deduplicate():
    class_names, overrides = parse_auto_mark_class_specs(
        ["Eye{first label}", "eye{final label}, hand"]
    )

    assert class_names == ["Eye", "hand"]
    assert overrides == {"eye": "final label"}


@pytest.mark.parametrize(
    "value",
    ["eye{", "{person eye}", "eye{}", "eye{person}extra", "eye{a{b}}"],
)
def test_auto_mark_class_specs_reject_malformed_overrides(value):
    with pytest.raises(PipelineValidationError, match="Invalid auto-marking class"):
        parse_auto_mark_class_specs(value)
