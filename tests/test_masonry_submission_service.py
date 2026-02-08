from taggui.widgets import image_list_masonry_submission_service as submission_module
from taggui.widgets.image_list_masonry_submission_service import MasonrySubmissionService


class FakeExecutor:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.submissions = []
        self.shutdown_calls = []

    def submit(self, fn, *args):
        if self.fail:
            raise RuntimeError("submit failed")
        self.submissions.append((fn, args))
        return "fake-future"

    def shutdown(self, wait=True):
        self.shutdown_calls.append(wait)


class FakeView:
    def __init__(self, executor):
        self._masonry_executor = executor
        self._masonry_calculating = True
        self._masonry_calc_future = None
        self._masonry_calc_count = 0


def test_prepare_executor_increments_without_recreate():
    view = FakeView(FakeExecutor())
    service = MasonrySubmissionService(view)

    service.prepare_executor()

    assert view._masonry_calc_count == 1
    assert isinstance(view._masonry_executor, FakeExecutor)


def test_prepare_executor_recreates_every_20(monkeypatch):
    old_executor = FakeExecutor()
    view = FakeView(old_executor)
    view._masonry_calc_count = 19
    service = MasonrySubmissionService(view)

    created_executors = []

    class NewExecutor(FakeExecutor):
        def __init__(self, max_workers=1):
            super().__init__()
            self.max_workers = max_workers
            created_executors.append(self)

    thread_starts = []

    class ThreadSpy:
        def __init__(self, target, daemon):
            self._target = target
            self.daemon = daemon

        def start(self):
            thread_starts.append(True)
            self._target()

    monkeypatch.setattr(submission_module, "ThreadPoolExecutor", NewExecutor)
    monkeypatch.setattr(submission_module.threading, "Thread", ThreadSpy)

    service.prepare_executor()

    assert view._masonry_calc_count == 20
    assert created_executors
    assert view._masonry_executor is created_executors[0]
    assert thread_starts == [True]
    assert old_executor.shutdown_calls == [True]


def test_submit_layout_job_rejects_invalid_items_data():
    executor = FakeExecutor()
    view = FakeView(executor)
    service = MasonrySubmissionService(view)

    ok = service.submit_layout_job(
        items_data=[("bad",), (1, 2)],
        column_width=100,
        spacing=2,
        num_columns=4,
        cache_key="k",
    )

    assert ok is False
    assert view._masonry_calculating is False
    assert executor.submissions == []


def test_submit_layout_job_success_submits_copy_and_sets_future():
    executor = FakeExecutor()
    view = FakeView(executor)
    service = MasonrySubmissionService(view)
    items = [(1, 1.2), (2, 0.8)]

    ok = service.submit_layout_job(
        items_data=items,
        column_width=128,
        spacing=2,
        num_columns=5,
        cache_key="abc",
    )

    assert ok is True
    assert view._masonry_calc_future == "fake-future"
    assert len(executor.submissions) == 1
    submitted_fn, args = executor.submissions[0]
    assert submitted_fn is submission_module.calculate_masonry_layout
    assert args[0] == items
    assert args[0] is not items  # defensive copy
    assert args[1:] == (128, 2, 5, "abc")


def test_submit_layout_job_handles_executor_exception():
    executor = FakeExecutor(fail=True)
    view = FakeView(executor)
    service = MasonrySubmissionService(view)

    ok = service.submit_layout_job(
        items_data=[(1, 1.0)],
        column_width=64,
        spacing=2,
        num_columns=3,
        cache_key="k2",
    )

    assert ok is False
    assert view._masonry_calculating is False
    assert view._masonry_calc_future is None
