import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "taggui"))

from utils.ideogram_caption import ideogram_caption_path
from utils.image_index_db import ImageIndexDB
from models.image_list_model import ImageListModel
from utils.quick_sort import (
    QUICK_SORT_SCHEMA_VERSION,
    QuickSortMapping,
    QuickSortProfile,
    QuickSortProfileStore,
    QuickSortSessionStore,
    QuickSortValidationError,
    default_quick_sort_profile,
    normalize_key_sequence,
)


def test_default_profile_is_zero_setup_full_keyboard_sort():
    profile = default_quick_sort_profile()

    profile.validate()

    assert profile.destinations == []
    assert profile.standard_key_destinations is True
    assert profile.mapping_for_key("a", qualifier=False).folder == "A"
    assert profile.mapping_for_key("9", qualifier=False).folder == "9"


def test_named_override_replaces_automatic_folder_and_can_disable_a_key():
    profile = default_quick_sort_profile()
    profile.destinations = [
        QuickSortMapping("Right Arm", "R", "Body/Right Arm"),
        QuickSortMapping("Unused", "X", "Unused", enabled=False),
    ]

    profile.validate()

    assert profile.mapping_for_key("r", qualifier=False).folder == "Body/Right Arm"
    assert profile.mapping_for_key("x", qualifier=False) is None


def test_quick_sort_session_store_round_trip_and_remove(tmp_path):
    store = QuickSortSessionStore(tmp_path / "sessions.json")
    state = {
        "profile_id": "profile-a",
        "directory_path": str(tmp_path),
        "items": [{"path": str(tmp_path / "a.png"), "state": "skipped"}],
    }

    store.put("session-a", state)

    assert store.get("session-a") == state
    store.remove("session-a")
    assert store.get("session-a") is None
from utils.quick_sort_file_service import (
    QuickSortAmbiguousSidecarError,
    QuickSortCollisionError,
    QuickSortFileError,
    QuickSortFileService,
)
import utils.quick_sort_file_service as quick_sort_file_service
from utils.sidecar import (
    legacy_json_sidecar_path,
    sidecar_backup_path,
    taggui_sidecar_path,
)


def _profile(tmp_path: Path, *, hierarchy_order: str = "destination_first"):
    destination = QuickSortMapping(
        id="route-right-arm",
        name="Right Arm",
        key="r",
        folder="Body/Right Arm",
        color="#62E7D8",
    )
    qualifier = QuickSortMapping(
        id="quality-high",
        name="High Quality",
        key="1",
        folder="Quality/High",
        color="#70D6A4",
    )
    profile = QuickSortProfile(
        id="profile-body-parts",
        name="Body Parts",
        standard_key_destinations=False,
        destinations=[destination],
        qualifiers=[qualifier],
        qualifier_enabled=True,
        qualifier_name="Quality",
        hierarchy_order=hierarchy_order,
        base_destination=str(tmp_path / "sorted"),
    )
    return profile, destination, qualifier


def _write_bundle(media_path: Path) -> dict[str, Path]:
    media_path.parent.mkdir(parents=True, exist_ok=True)
    paths = {
        "media": media_path,
        "txt": media_path.with_suffix(".txt"),
        "taggui": taggui_sidecar_path(media_path),
        "legacy_json": legacy_json_sidecar_path(media_path),
        "ideogram": ideogram_caption_path(media_path),
    }
    paths["media"].write_bytes(b"image-bytes")
    paths["txt"].write_text("right arm, hand", encoding="utf-8")
    paths["taggui"].write_text('{"version":1}', encoding="utf-8")
    paths["legacy_json"].write_text('{"nodes":[]}', encoding="utf-8")
    paths["ideogram"].write_text(
        '{"high_level_description":"arm"}', encoding="utf-8"
    )
    return paths


def test_profile_store_round_trip_preserves_versioned_profile(tmp_path):
    profile, _destination, _qualifier = _profile(tmp_path)
    store = QuickSortProfileStore(tmp_path / "profiles.json")

    store.save([profile])
    restored = store.load()

    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == QUICK_SORT_SCHEMA_VERSION
    assert len(restored) == 1
    assert restored[0].to_dict() == profile.to_dict()
    assert restored[0].destinations[0].key == "R"


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("shift+ctrl+r", "Ctrl+Shift+R"),
        ("+", "+"),
        ("control++", "Ctrl++"),
    ],
)
def test_key_sequences_are_canonical_and_keep_plus_key(raw, normalized):
    assert normalize_key_sequence(raw) == normalized


def test_profile_validation_rejects_duplicate_keys_within_one_stage(tmp_path):
    profile, destination, _qualifier = _profile(tmp_path)
    profile.destinations.append(
        QuickSortMapping(
            id="route-reject",
            name="Reject",
            key="R",
            folder="Reject",
        )
    )

    with pytest.raises(QuickSortValidationError, match="assigned to both"):
        profile.validate()

    assert destination.key == "R"


@pytest.mark.parametrize(
    ("key", "folder", "message"),
    [
        ("Space", "Right Arm", "reserved for Quick Sort"),
        ("R", "CON", "reserved folder name"),
        ("R", "Right:Arm", "invalid in folder names"),
    ],
)
def test_profile_validation_surfaces_unusable_keys_and_folders(
    tmp_path,
    key,
    folder,
    message,
):
    profile, destination, _qualifier = _profile(tmp_path)
    destination.key = key
    destination.folder = folder

    with pytest.raises(QuickSortValidationError, match=message):
        profile.validate()


@pytest.mark.parametrize("folder", ["../Outside", "Body/../Outside"])
def test_profile_validation_rejects_route_folders_that_escape_base(
    tmp_path, folder
):
    profile, destination, _qualifier = _profile(tmp_path)
    destination.folder = folder

    with pytest.raises(QuickSortValidationError, match="cannot contain"):
        profile.validate()


def test_qualifier_and_destination_keys_are_resolved_by_stage(tmp_path):
    profile, destination, qualifier = _profile(tmp_path)
    profile.validate()

    chosen_qualifier = profile.mapping_for_key("1", qualifier=True)
    chosen_destination = profile.mapping_for_key("r", qualifier=False)

    assert chosen_qualifier is qualifier
    assert chosen_destination is destination
    assert profile.mapping_for_key("R", qualifier=True) is None
    assert profile.mapping_for_key("1", qualifier=False) is None
    assert profile.route_directory(
        chosen_destination, chosen_qualifier
    ) == (
        tmp_path
        / "sorted"
        / "Body"
        / "Right Arm"
        / "Quality"
        / "High"
    ).resolve()


def test_unclassified_routes_reject_cross_stage_key_ambiguity(tmp_path):
    profile, destination, qualifier = _profile(tmp_path)
    profile.missing_qualifier = "unclassified"
    qualifier.key = destination.key

    with pytest.raises(QuickSortValidationError, match="ambiguous between qualifier"):
        profile.validate()


def test_profile_supports_qualifier_first_and_unclassified_routes(tmp_path):
    profile, destination, qualifier = _profile(
        tmp_path, hierarchy_order="qualifier_first"
    )

    assert profile.route_directory(destination, qualifier) == (
        tmp_path
        / "sorted"
        / "Quality"
        / "High"
        / "Body"
        / "Right Arm"
    ).resolve()

    profile.missing_qualifier = "unclassified"
    profile.unclassified_folder = "Quality/Unclassified"
    assert profile.route_directory(destination) == (
        tmp_path
        / "sorted"
        / "Quality"
        / "Unclassified"
        / "Body"
        / "Right Arm"
    ).resolve()


def test_profile_requires_qualifier_before_destination_when_configured(tmp_path):
    profile, destination, _qualifier = _profile(tmp_path)

    with pytest.raises(QuickSortValidationError, match="Choose quality"):
        profile.route_directory(destination)


def test_move_transfers_full_sidecar_bundle_and_supports_undo_redo(tmp_path):
    source_bundle = _write_bundle(tmp_path / "source" / "arm.png")
    destination_directory = tmp_path / "sorted" / "Right Arm"
    service = QuickSortFileService()

    result = service.execute(
        source=source_bundle["media"],
        destination_directory=destination_directory,
        mode="move",
        include_sidecars=True,
        collision_policy="append",
    )

    assert result.operation is not None
    assert len(result.operation.bundle_pairs) == len(source_bundle)
    for source, destination in result.operation.bundle_pairs:
        assert not source.exists()
        assert destination.exists()

    service.undo(result.operation)
    for source, destination in result.operation.bundle_pairs:
        assert source.exists()
        assert not destination.exists()

    service.redo(result.operation)
    for source, destination in result.operation.bundle_pairs:
        assert not source.exists()
        assert destination.exists()


def test_copy_preserves_source_bundle_and_undo_removes_only_outputs(tmp_path):
    source_bundle = _write_bundle(tmp_path / "source" / "arm.png")
    destination_directory = tmp_path / "sorted" / "Right Arm"
    service = QuickSortFileService()

    result = service.execute(
        source=source_bundle["media"],
        destination_directory=destination_directory,
        mode="copy",
        include_sidecars=True,
        collision_policy="append",
    )

    assert result.operation is not None
    for source, destination in result.operation.bundle_pairs:
        assert source.exists()
        assert destination.exists()
        assert destination.read_bytes() == source.read_bytes()

    service.undo(result.operation)
    for source, destination in result.operation.bundle_pairs:
        assert source.exists()
        assert not destination.exists()

    service.redo(result.operation)
    for source, destination in result.operation.bundle_pairs:
        assert source.exists()
        assert destination.exists()


def test_copy_undo_refuses_to_delete_an_output_modified_after_copy(tmp_path):
    source = tmp_path / "source" / "arm.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"original")
    service = QuickSortFileService()
    result = service.execute(
        source=source,
        destination_directory=tmp_path / "sorted",
        mode="copy",
        include_sidecars=False,
        collision_policy="append",
    )
    operation = result.operation
    assert operation is not None
    destination = operation.destination
    destination.write_bytes(b"externally modified")

    with pytest.raises(QuickSortFileError, match="modified or replaced"):
        service.undo(operation)

    assert source.read_bytes() == b"original"
    assert destination.read_bytes() == b"externally modified"


@pytest.mark.parametrize("mode", ["move", "copy"])
def test_symlink_sources_move_or_copy_the_link_itself(tmp_path, mode):
    target = tmp_path / "outside" / "target.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"target")
    source = tmp_path / "source" / "alias.png"
    source.parent.mkdir()
    try:
        source.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Symlinks are unavailable: {exc}")
    original_link_target = os.readlink(source)
    service = QuickSortFileService()

    result = service.execute(
        source=source,
        destination_directory=tmp_path / "sorted",
        mode=mode,
        include_sidecars=False,
        collision_policy="append",
    )

    operation = result.operation
    assert operation is not None
    destination = operation.destination
    assert destination.name == "alias.png"
    assert destination.is_symlink()
    assert os.readlink(destination) == original_link_target
    assert target.read_bytes() == b"target"
    assert os.path.lexists(source) is (mode == "copy")

    service.undo(operation)
    assert source.is_symlink()
    assert os.readlink(source) == original_link_target
    assert not os.path.lexists(destination)


def test_dangling_destination_symlink_counts_as_a_collision(tmp_path):
    source = tmp_path / "source" / "arm.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    destination_directory = tmp_path / "sorted"
    destination_directory.mkdir()
    destination = destination_directory / source.name
    try:
        destination.symlink_to(tmp_path / "missing-target.png")
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Symlinks are unavailable: {exc}")

    result = QuickSortFileService().execute(
        source=source,
        destination_directory=destination_directory,
        mode="move",
        include_sidecars=False,
        collision_policy="skip",
    )

    assert result.skipped
    assert source.read_bytes() == b"source"
    assert destination.is_symlink()


def test_backup_artifacts_stay_with_the_original_during_copy(tmp_path):
    bundle = _write_bundle(tmp_path / "source" / "arm.png")
    media_backup = bundle["media"].with_suffix(".png.backup")
    metadata_backup = sidecar_backup_path(bundle["taggui"])
    media_backup.write_bytes(b"media backup")
    metadata_backup.write_bytes(b"metadata backup")
    service = QuickSortFileService()

    result = service.execute(
        source=bundle["media"],
        destination_directory=tmp_path / "sorted",
        mode="copy",
        include_sidecars=True,
        collision_policy="append",
    )

    operation = result.operation
    assert operation is not None
    bundled_sources = {source for source, _destination in operation.bundle_pairs}
    assert media_backup not in bundled_sources
    assert metadata_backup not in bundled_sources
    assert media_backup.read_bytes() == b"media backup"
    assert metadata_backup.read_bytes() == b"metadata backup"
    assert not (tmp_path / "sorted" / media_backup.name).exists()
    assert not (tmp_path / "sorted" / metadata_backup.name).exists()
    service.undo(operation)


def test_append_collision_checks_sidecars_when_media_name_is_free(tmp_path):
    source = tmp_path / "source" / "arm.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"image")
    source.with_suffix(".txt").write_text("caption", encoding="utf-8")
    destination_directory = tmp_path / "sorted"
    destination_directory.mkdir()
    occupied_sidecar = destination_directory / "arm.txt"
    occupied_sidecar.write_text("keep me", encoding="utf-8")

    result = QuickSortFileService().execute(
        source=source,
        destination_directory=destination_directory,
        mode="copy",
        include_sidecars=True,
        collision_policy="append",
    )

    assert result.operation is not None
    assert result.operation.destination.name == "arm (1).png"
    assert (destination_directory / "arm (1).txt").read_text(
        encoding="utf-8"
    ) == "caption"
    assert occupied_sidecar.read_text(encoding="utf-8") == "keep me"


def test_skip_collision_leaves_source_and_existing_destination_untouched(tmp_path):
    source = tmp_path / "source" / "arm.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    destination_directory = tmp_path / "sorted"
    destination_directory.mkdir()
    destination = destination_directory / source.name
    destination.write_bytes(b"existing")

    result = QuickSortFileService().execute(
        source=source,
        destination_directory=destination_directory,
        mode="move",
        include_sidecars=False,
        collision_policy="skip",
    )

    assert result.skipped is True
    assert result.operation is None
    assert source.read_bytes() == b"source"
    assert destination.read_bytes() == b"existing"


def test_ask_collision_raises_without_overwriting(tmp_path):
    source = tmp_path / "source" / "arm.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    destination_directory = tmp_path / "sorted"
    destination_directory.mkdir()
    destination = destination_directory / source.name
    destination.write_bytes(b"existing")

    with pytest.raises(QuickSortCollisionError, match="already exists"):
        QuickSortFileService().execute(
            source=source,
            destination_directory=destination_directory,
            mode="copy",
            include_sidecars=False,
            collision_policy="ask",
        )

    assert source.read_bytes() == b"source"
    assert destination.read_bytes() == b"existing"


def test_move_rolls_back_completed_companions_when_media_move_fails(
    tmp_path, monkeypatch
):
    source = tmp_path / "source" / "arm.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"image")
    caption = source.with_suffix(".txt")
    caption.write_text("caption", encoding="utf-8")
    destination_directory = tmp_path / "sorted"
    real_move = shutil.move

    def fail_media_move(source_path, destination_path, *args, **kwargs):
        if Path(source_path) == source:
            Path(destination_path).write_bytes(b"partial destination")
            raise OSError("injected media move failure")
        return real_move(source_path, destination_path, *args, **kwargs)

    monkeypatch.setattr(quick_sort_file_service.shutil, "move", fail_media_move)

    with pytest.raises(QuickSortFileError, match="injected media move failure"):
        QuickSortFileService().execute(
            source=source,
            destination_directory=destination_directory,
            mode="move",
            include_sidecars=True,
            collision_policy="append",
        )

    assert source.read_bytes() == b"image"
    assert caption.read_text(encoding="utf-8") == "caption"
    assert not (destination_directory / source.name).exists()
    assert not (destination_directory / caption.name).exists()


def test_copy_cleans_the_current_partial_destination_on_failure(
    tmp_path, monkeypatch
):
    source = tmp_path / "source" / "arm.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"image")
    destination_directory = tmp_path / "sorted"

    def fail_after_partial_copy(source_path, destination_path, **_kwargs):
        Path(destination_path).write_bytes(b"partial")
        raise OSError("injected partial copy failure")

    monkeypatch.setattr(
        quick_sort_file_service.shutil,
        "copy2",
        fail_after_partial_copy,
    )

    with pytest.raises(QuickSortFileError, match="partial copy failure"):
        QuickSortFileService().execute(
            source=source,
            destination_directory=destination_directory,
            mode="copy",
            include_sidecars=False,
            collision_policy="append",
        )

    assert source.read_bytes() == b"image"
    assert not os.path.lexists(destination_directory / source.name)


@pytest.mark.parametrize("mode", ["move", "copy"])
def test_identity_capture_failure_rolls_back_the_completed_operation(
    tmp_path, monkeypatch, mode
):
    source = tmp_path / "source" / "arm.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"image")
    destination_directory = tmp_path / "sorted"

    def fail_identity_capture(_cls, _path):
        raise OSError("injected lstat failure")

    monkeypatch.setattr(
        quick_sort_file_service.QuickSortDestinationIdentity,
        "capture",
        classmethod(fail_identity_capture),
    )

    with pytest.raises(QuickSortFileError, match="record destination identity"):
        QuickSortFileService().execute(
            source=source,
            destination_directory=destination_directory,
            mode=mode,
            include_sidecars=False,
            collision_policy="append",
        )

    assert source.read_bytes() == b"image"
    assert not os.path.lexists(destination_directory / source.name)


def test_shared_stem_sidecars_are_rejected_instead_of_stolen(tmp_path):
    source = tmp_path / "source" / "arm.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"png")
    source.with_suffix(".jpg").write_bytes(b"jpg")
    source.with_suffix(".txt").write_text("shared", encoding="utf-8")

    with pytest.raises(QuickSortAmbiguousSidecarError, match="share sidecars"):
        QuickSortFileService().execute(
            source=source,
            destination_directory=tmp_path / "sorted",
            mode="move",
            include_sidecars=True,
            collision_policy="append",
        )

    assert source.exists()
    assert source.with_suffix(".jpg").exists()
    assert source.with_suffix(".txt").exists()


def test_copy_metadata_clone_preserves_curator_index_state(tmp_path):
    source = tmp_path / "source.png"
    destination = tmp_path / "copy.png"
    source.write_bytes(b"source")
    destination.write_bytes(b"copy")
    database = ImageIndexDB(tmp_path)
    if not database.enabled:
        pytest.skip("Dimension/index cache is disabled in this test environment")
    try:
        database.bulk_insert_files([source, destination], tmp_path)
        source_id = database.get_image_id(source.name)
        destination_id = database.get_image_id(destination.name)
        assert source_id is not None and destination_id is not None
        database.set_tags_for_image(source_id, ["zebra", "apple", "middle"])
        database.set_rating(source_id, 4.5, reaction_updated_at=123.0)
        database.set_reactions(
            source_id,
            love=True,
            bomb=False,
            reaction_updated_at=123.0,
        )
        database.set_review_state(
            source_id,
            review_rank=2,
            review_flags=1,
            review_updated_at=456.0,
        )
        database.set_markings_for_image(
            source_id,
            [
                {
                    "label": "arm",
                    "type": "rectangle",
                    "confidence": 0.9,
                    "rect": [1, 2, 30, 40],
                }
            ],
        )

        assert database.clone_curator_metadata(source.name, destination.name)

        source_row = database.get_image_by_id(source_id)
        destination_row = database.get_image_by_id(destination_id)
        for field in (
            "rating",
            "love",
            "bomb",
            "reaction_updated_at",
            "review_rank",
            "review_flags",
            "review_updated_at",
        ):
            assert destination_row[field] == source_row[field]
        assert database.get_tags_for_image(destination_id) == [
            "zebra",
            "apple",
            "middle",
        ]
        marking = database.conn.execute(
            "SELECT label, type, confidence, x, y, width, height "
            "FROM image_markings WHERE image_id = ?",
            (destination_id,),
        ).fetchone()
        assert tuple(marking) == (
            "arm",
            "rectangle",
            0.9,
            1,
            2,
            30,
            40,
        )
    finally:
        database.close()


def test_rename_collision_keeps_both_database_rows_and_source_metadata(tmp_path):
    source = tmp_path / "source.png"
    destination = tmp_path / "destination.png"
    source.write_bytes(b"source")
    destination.write_bytes(b"destination")
    database = ImageIndexDB(tmp_path)
    if not database.enabled:
        pytest.skip("Dimension/index cache is disabled in this test environment")
    try:
        database.bulk_insert_files([source, destination], tmp_path)
        source_id = database.get_image_id(source.name)
        destination_id = database.get_image_id(destination.name)
        assert source_id is not None and destination_id is not None
        database.set_tags_for_image(source_id, ["keep me"])

        assert not database.rename_image_path(
            source.name,
            destination.name,
            directory_path=tmp_path,
        )

        assert database.get_image_id(source.name) == source_id
        assert database.get_image_id(destination.name) == destination_id
        assert database.get_tags_for_image(source_id) == ["keep me"]
    finally:
        database.close()


def test_quick_sort_relocation_replaces_stale_destination_row_atomically(tmp_path):
    source = tmp_path / "source.png"
    destination = tmp_path / "sorted" / "source.png"
    stale_destination = tmp_path / "stale.png"
    source.write_bytes(b"source")
    stale_destination.write_bytes(b"stale")
    database = ImageIndexDB(tmp_path)
    if not database.enabled:
        pytest.skip("Dimension/index cache is disabled in this test environment")
    try:
        database.bulk_insert_files([source, stale_destination], tmp_path)
        source_id = database.get_image_id(source.name)
        stale_id = database.get_image_id(stale_destination.name)
        assert source_id is not None and stale_id is not None
        database.set_tags_for_image(source_id, ["keep source metadata"])
        database.set_tags_for_image(stale_id, ["discard stale metadata"])
        database.rename_image_path(
            stale_destination.name,
            str(destination.relative_to(tmp_path)),
            directory_path=tmp_path,
        )

        destination.parent.mkdir(parents=True)
        source.rename(destination)
        assert database.rename_image_path(
            source.name,
            str(destination.relative_to(tmp_path)),
            directory_path=tmp_path,
            replace_stale_destination=True,
        )

        assert database.get_image_id(source.name) is None
        assert database.get_image_id(str(destination.relative_to(tmp_path))) == source_id
        assert database.get_tags_for_image(source_id) == ["keep source metadata"]
        assert database.get_image_by_id(stale_id) is None
    finally:
        database.close()


def test_generated_media_registration_hydrates_taggui_sidecar_index(tmp_path):
    media_path = tmp_path / "sorted" / "image.png"
    media_path.parent.mkdir()
    media_path.write_bytes(b"image")
    sidecar_path = taggui_sidecar_path(media_path)
    sidecar_path.write_text(
        json.dumps(
            {
                "version": 1,
                "rating": 5,
                "love": True,
                "bomb": False,
                "review_rank": 2,
                "review_flags": 1,
                "markings": [
                    {
                        "label": "arm",
                        "type": "RECTANGLE",
                        "confidence": 0.75,
                        "rect": [1, 2, 30, 40],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    database = ImageIndexDB(tmp_path)
    if not database.enabled:
        pytest.skip("Dimension/index cache is disabled in this test environment")
    try:
        database.bulk_insert_files([media_path], tmp_path)
        relative_path = str(media_path.relative_to(tmp_path))
        model = SimpleNamespace(
            _db=database,
            _directory_path=tmp_path,
            _preferred_sidecar_meta_path=lambda _path: sidecar_path,
            _read_cached_sidecar_meta=lambda path: json.loads(
                path.read_text(encoding="utf-8")
            ),
        )

        ImageListModel._hydrate_generated_media_sidecar_index(
            model,
            [relative_path],
        )

        image_id = database.get_image_id(relative_path)
        assert image_id is not None
        row = database.get_image_by_id(image_id)
        assert row["rating"] == 1.0
        assert row["love"] == 1
        assert row["bomb"] == 0
        assert row["review_rank"] == 2
        assert row["review_flags"] == 1
        marking = database.conn.execute(
            "SELECT label, type, confidence, x, y, width, height "
            "FROM image_markings WHERE image_id = ?",
            (image_id,),
        ).fetchone()
        assert tuple(marking) == (
            "arm",
            "rectangle",
            0.75,
            1,
            2,
            30,
            40,
        )
    finally:
        database.close()


def test_path_mutations_invalidate_the_materialized_order_cache(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    database = ImageIndexDB(tmp_path)
    if not database.enabled:
        pytest.skip("Dimension/index cache is disabled in this test environment")

    def seed_cache(image_id):
        database.conn.execute(
            "INSERT INTO ordered_image_cache(cache_key, rank, image_id) "
            "VALUES ('test-order', 0, ?)",
            (image_id,),
        )
        database.conn.commit()
        database._order_cache_signature = ("test-order",)

    def assert_cache_invalidated():
        count = database.conn.execute(
            "SELECT COUNT(*) FROM ordered_image_cache"
        ).fetchone()[0]
        assert count == 0
        assert database._order_cache_signature is None

    try:
        database.bulk_insert_files([source], tmp_path)
        source_id = database.get_image_id(source.name)
        assert source_id is not None

        seed_cache(source_id)
        added = tmp_path / "added.png"
        added.write_bytes(b"added")
        database.bulk_insert_files([added], tmp_path)
        assert_cache_invalidated()

        seed_cache(source_id)
        renamed = tmp_path / "renamed.png"
        source.rename(renamed)
        assert database.rename_image_path(
            source.name,
            renamed.name,
            directory_path=tmp_path,
        )
        assert_cache_invalidated()

        seed_cache(source_id)
        assert database.remove_images_by_paths([renamed.name]) == 1
        assert_cache_invalidated()
    finally:
        database.close()
