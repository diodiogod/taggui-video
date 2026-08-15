from utils.quick_tag import (
    QuickTagMapping,
    QuickTagProfile,
    QuickTagProfileStore,
    QuickTagValidationError,
    builtin_quick_tag_profiles,
    clone_quick_tag_profile,
    reconcile_quick_tag_profiles,
    edit_ordered_tag,
    merge_ordered_tags,
)


def test_ordered_tag_merge_and_inline_edit():
    assert merge_ordered_tags(["cat", "small"], ["blue", "cat"]) == [
        "cat",
        "small",
        "blue",
    ]
    assert edit_ordered_tag(["cat", "small"], 1, "blue") == ["cat", "blue"]
    assert edit_ordered_tag(["cat", "small"], 1, "blue", insert=True) == [
        "cat",
        "blue",
        "small",
    ]


def test_quick_tag_profile_rejects_control_key_collision():
    profile = QuickTagProfile(
        name="Test",
        mappings=[QuickTagMapping(tag="cat", key="Tab")],
    )
    try:
        profile.validate()
    except QuickTagValidationError as exc:
        assert "reserved" in str(exc)
    else:
        raise AssertionError("reserved control key was accepted as a tag shortcut")


def test_quick_tag_profile_store_round_trip(tmp_path):
    profile = QuickTagProfile(
        name="Animals",
        mappings=[QuickTagMapping(tag="cat", key="C", color="#62E7D8")],
    )
    store = QuickTagProfileStore(tmp_path / "profiles.json")
    store.save([profile])
    loaded = store.load()
    assert loaded[0].name == "Animals"
    assert loaded[0].mappings[0].tag == "cat"
    assert loaded[0].refine_key == "Tab"


def test_composition_preset_uses_memorable_shot_keys_and_fresh_ids():
    preset = next(item for item in builtin_quick_tag_profiles() if item.name.startswith("Composition"))
    mapping_keys = {mapping.key: mapping.tag for mapping in preset.mappings}
    assert mapping_keys["C"] == "close-up"
    assert mapping_keys["K"] == "cowboy shot"
    assert mapping_keys["F"] == "full body"
    assert mapping_keys["W"] == "wide shot"

    clone = clone_quick_tag_profile(preset)
    assert clone.id != preset.id
    assert {mapping.id for mapping in clone.mappings}.isdisjoint(
        {mapping.id for mapping in preset.mappings}
    )


def test_builtin_presets_cover_common_labeling_workflows():
    presets = {profile.name: profile for profile in builtin_quick_tag_profiles()}
    assert {
        "General image labeling",
        "Portrait / Character",
        "Clothing / Body parts",
        "Quality review",
        "Composition / Shot sizes",
    } <= presets.keys()
    quality = {mapping.key: mapping.tag for mapping in presets["Quality review"].mappings}
    assert quality["H"] == "high-quality"
    assert quality["L"] == "low-quality"


def test_old_exact_preset_copies_are_collapsed_and_marked_custom():
    template = builtin_quick_tag_profiles()[-1]
    first = clone_quick_tag_profile(template)
    second = clone_quick_tag_profile(template)
    second.name = f"{template.name} 2"
    reconciled, changed = reconcile_quick_tag_profiles(
        [first, second],
        builtin_quick_tag_profiles(),
    )
    assert changed
    assert len(reconciled) == 1
    assert reconciled[0].template_key == "composition_shot_sizes"
    assert reconciled[0].name == "Composition / Shot sizes (custom)"
