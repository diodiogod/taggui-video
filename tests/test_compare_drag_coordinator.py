from taggui.widgets.compare_drag_coordinator import CompareDragCoordinator


def test_hold_reaches_ready_after_threshold():
    coordinator = CompareDragCoordinator(hold_seconds=2.0)
    coordinator.begin_drag("source", now=0.0)
    state = coordinator.update_target("target", blocked=False, now=0.0)
    assert state["state"] == "hovering"
    assert state["ready"] is False

    state = coordinator.update_target("target", blocked=False, now=2.0)
    assert state["state"] == "ready"
    assert state["ready"] is True
    assert state["progress"] == 1.0


def test_target_switch_resets_hold_progress():
    coordinator = CompareDragCoordinator(hold_seconds=2.0)
    coordinator.begin_drag("source", now=0.0)
    state = coordinator.update_target("target_a", blocked=False, now=1.2)
    assert 0.5 < state["progress"] < 1.0

    state = coordinator.update_target("target_b", blocked=False, now=1.3)
    assert state["target_key"] == "target_b"
    assert state["progress"] == 0.0
    assert state["ready"] is False


def test_leaving_target_clears_progress():
    coordinator = CompareDragCoordinator(hold_seconds=2.0)
    coordinator.begin_drag("source", now=0.0)
    coordinator.update_target("target", blocked=False, now=1.0)
    state = coordinator.update_target(None, blocked=False, now=1.2)
    assert state["state"] == "none"
    assert state["progress"] == 0.0
    assert state["target_key"] is None


def test_blocked_target_never_reports_ready():
    coordinator = CompareDragCoordinator(hold_seconds=2.0)
    coordinator.begin_drag("source", now=0.0)
    state = coordinator.update_target("target", blocked=True, now=8.0)
    assert state["state"] == "blocked"
    assert state["ready"] is False


def test_release_before_ready_falls_back():
    coordinator = CompareDragCoordinator(hold_seconds=2.0)
    coordinator.begin_drag("source", now=0.0)
    coordinator.update_target("target", blocked=False, now=1.0)
    result = coordinator.release_drag(now=1.2)
    assert result["handled"] is False
    assert coordinator.active is False


def test_release_after_ready_is_handled():
    coordinator = CompareDragCoordinator(hold_seconds=2.0)
    coordinator.begin_drag("source", now=0.0)
    coordinator.update_target("target", blocked=False, now=2.0)
    result = coordinator.release_drag(now=2.0)
    assert result["handled"] is True
    assert result["target_key"] == "target"
    assert coordinator.active is False
