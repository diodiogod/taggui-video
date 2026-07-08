from taggui.widgets.compare_drag_coordinator import CompareTargetCandidate, select_best_target


def test_select_best_target_prefers_floating_over_main():
    candidates = [
        CompareTargetCandidate(key="main", kind="main", order=10),
        CompareTargetCandidate(key="floating_1", kind="floating", order=1),
    ]
    best = select_best_target(candidates)
    assert best is not None
    assert best.key == "floating_1"


def test_select_best_target_excludes_source_key():
    candidates = [
        CompareTargetCandidate(key="floating_source", kind="floating", order=4),
        CompareTargetCandidate(key="floating_target", kind="floating", order=2),
    ]
    best = select_best_target(candidates, source_key="floating_source")
    assert best is not None
    assert best.key == "floating_target"


def test_select_best_target_falls_back_to_main_when_no_floating():
    candidates = [CompareTargetCandidate(key="main", kind="main", order=0)]
    best = select_best_target(candidates)
    assert best is not None
    assert best.key == "main"
