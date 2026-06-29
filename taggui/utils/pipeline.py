"""Versioned automation pipeline definitions and profile persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import tempfile
from typing import Any
from uuid import uuid4

PIPELINE_SCHEMA_VERSION = 1
PIPELINE_STEP_TYPES = (
    "auto_mark",
    "build_ideogram_regions",
    "auto_caption",
    "save",
)


class PipelineValidationError(ValueError):
    """Raised when a pipeline profile cannot be validated."""


def parse_auto_mark_class_specs(
    value: str | list[str] | tuple[str, ...],
) -> tuple[list[str], dict[str, str]]:
    """Parse ``source{output label}`` class filters used by auto-mark steps."""
    raw_entries = value if isinstance(value, (list, tuple)) else [value]
    entries = [
        part.strip()
        for raw_entry in raw_entries
        for part in str(raw_entry or "").split(",")
        if part.strip()
    ]
    class_names: list[str] = []
    label_overrides: dict[str, str] = {}
    seen_names: set[str] = set()

    for entry in entries:
        if "{" not in entry and "}" not in entry:
            source_name = entry
            output_label = None
        else:
            opening = entry.find("{")
            if (
                opening <= 0
                or not entry.endswith("}")
                or "{" in entry[opening + 1:-1]
                or "}" in entry[:opening]
                or "}" in entry[opening + 1:-1]
            ):
                raise PipelineValidationError(
                    f"Invalid auto-marking class entry {entry!r}. "
                    "Use source_class{output label}."
                )
            source_name = entry[:opening].strip()
            output_label = entry[opening + 1:-1].strip()
            if not source_name or not output_label:
                raise PipelineValidationError(
                    f"Invalid auto-marking class entry {entry!r}. "
                    "Both the source class and output label are required."
                )

        normalized_name = source_name.casefold()
        if normalized_name not in seen_names:
            seen_names.add(normalized_name)
            class_names.append(source_name)
        if output_label is not None:
            label_overrides[normalized_name] = output_label

    return class_names, label_overrides


def new_pipeline_id(prefix: str = "pipeline") -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


@dataclass
class PipelineStep:
    type: str
    settings: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    id: str = field(default_factory=lambda: new_pipeline_id("step"))

    def validate(self) -> None:
        if self.type not in PIPELINE_STEP_TYPES:
            raise PipelineValidationError(f"Unsupported pipeline step type: {self.type!r}")
        if not str(self.id or "").strip():
            raise PipelineValidationError("Pipeline steps require a stable ID.")
        if not isinstance(self.settings, dict):
            raise PipelineValidationError("Pipeline step settings must be an object.")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "id": self.id,
            "type": self.type,
            "enabled": bool(self.enabled),
            "settings": dict(self.settings),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PipelineStep":
        if not isinstance(payload, dict):
            raise PipelineValidationError("Pipeline steps must be JSON objects.")
        raw_settings = payload.get("settings", {})
        if not isinstance(raw_settings, dict):
            raise PipelineValidationError("Pipeline step settings must be an object.")
        step = cls(
            id=str(payload.get("id") or new_pipeline_id("step")),
            type=str(payload.get("type") or ""),
            enabled=bool(payload.get("enabled", True)),
            settings=dict(raw_settings),
        )
        step.validate()
        return step


@dataclass
class PipelineDefinition:
    name: str
    steps: list[PipelineStep] = field(default_factory=list)
    id: str = field(default_factory=new_pipeline_id)
    schema_version: int = PIPELINE_SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != PIPELINE_SCHEMA_VERSION:
            raise PipelineValidationError(
                f"Unsupported pipeline schema version: {self.schema_version}"
            )
        if not str(self.name or "").strip():
            raise PipelineValidationError("Pipeline name cannot be empty.")
        if not str(self.id or "").strip():
            raise PipelineValidationError("Pipeline requires a stable ID.")
        seen_ids: set[str] = set()
        for step in self.steps:
            step.validate()
            if step.id in seen_ids:
                raise PipelineValidationError(f"Duplicate pipeline step ID: {step.id}")
            seen_ids.add(step.id)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "name": self.name.strip(),
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PipelineDefinition":
        if not isinstance(payload, dict):
            raise PipelineValidationError("Pipeline profiles must be JSON objects.")
        try:
            schema_version = int(payload.get("schema_version", PIPELINE_SCHEMA_VERSION))
        except (TypeError, ValueError) as exc:
            raise PipelineValidationError("Pipeline schema version must be an integer.") from exc
        raw_steps = payload.get("steps", [])
        if not isinstance(raw_steps, list):
            raise PipelineValidationError("Pipeline steps must be a list.")
        pipeline = cls(
            schema_version=schema_version,
            id=str(payload.get("id") or new_pipeline_id()),
            name=str(payload.get("name") or ""),
            steps=[PipelineStep.from_dict(step) for step in raw_steps],
        )
        pipeline.validate()
        return pipeline


def default_pipeline(name: str = "Ideogram marking pass") -> PipelineDefinition:
    return PipelineDefinition(
        name=name,
        steps=[
            PipelineStep("auto_mark"),
            PipelineStep("build_ideogram_regions"),
            PipelineStep("auto_caption", {"output_format": "Ideogram 4 JSON"}),
            PipelineStep("save"),
        ],
    )


class PipelineStore:
    """Atomic JSON persistence for named pipeline profiles."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else self.default_path()

    @staticmethod
    def default_path() -> Path:
        app_data = os.getenv("APPDATA")
        if app_data:
            base = Path(app_data) / "taggui"
        else:
            config_home = os.getenv("XDG_CONFIG_HOME")
            base = (
                Path(config_home) / "taggui"
                if config_home
                else Path.home() / ".config" / "taggui"
            )
        return base / "pipelines.json"

    def load(self) -> list[PipelineDefinition]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PipelineValidationError(
                f"Cannot read pipeline profiles from {self.path}: {exc}"
            ) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("pipelines"), list):
            raise PipelineValidationError("Pipeline profile file has an invalid root structure.")
        return [PipelineDefinition.from_dict(item) for item in payload["pipelines"]]

    def save(self, pipelines: list[PipelineDefinition]) -> None:
        for pipeline in pipelines:
            pipeline.validate()
        payload = {
            "schema_version": PIPELINE_SCHEMA_VERSION,
            "pipelines": [pipeline.to_dict() for pipeline in pipelines],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                json.dump(payload, temporary_file, ensure_ascii=False, indent=2)
                temporary_file.write("\n")
                temporary_path = Path(temporary_file.name)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
