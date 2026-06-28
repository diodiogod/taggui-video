import json

import pytest

from taggui.utils.pipeline import (
    PipelineDefinition,
    PipelineStep,
    PipelineStore,
    PipelineValidationError,
    default_pipeline,
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
