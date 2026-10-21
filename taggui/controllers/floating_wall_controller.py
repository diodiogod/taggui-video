"""Wall layout preferences and cancellable, geometry-only resize reflow."""
import weakref
from contextlib import ExitStack

from PySide6.QtCore import QObject, QEvent, QRect, Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QCursor
from PySide6.QtWidgets import QApplication, QToolTip
from shiboken6 import isValid

from utils.latest_task import LatestTask
from utils.settings import DEFAULT_SETTINGS, settings
from widgets.floating_wall_packing import ALGORITHMS, pack_wall, maxrects_available


def _calculate(payload, cancelled):
    ratios, bounds, options = payload
    return pack_wall(ratios, bounds, cancelled=cancelled, **options)


class FloatingWallController(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.algorithm_override = None
        self.last_result = None
        self._pending = None
        self._applying = False
        self._menus = []
        self.worker = LatestTask(self, name='wall-layout')
        self.worker.completed.connect(self._apply_result)
        self.manual_action = QAction('Manual Wall Layout', host)
        self.manual_action.setCheckable(True)
        self.manual_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.manual_action.setShortcut(QKeySequence(self.setting('floating_wall_manual_shortcut')))
        self.manual_action.setToolTip('Suspend automatic wall rearrangement until turned off. Hold Alt for one gesture.')
        self.manual_action.toggled.connect(self._manual_changed)
        host.addAction(self.manual_action)
        settings.change.connect(self._setting_changed)

    @staticmethod
    def setting(key):
        default = DEFAULT_SETTINGS[key]
        return settings.value(key, default, type=type(default))

    @property
    def algorithm(self):
        return self.algorithm_override or self.setting('floating_wall_algorithm')

    def _manual_changed(self, enabled):
        self.cancel()
        self.show_message(
            'Manual wall layout: automatic rearrangement suspended.' if enabled else
            'Automatic wall layout resumed for the next resize.', duration_ms=4000)

    def show_message(self, message, source=None, *, duration_ms=5000):
        """Display transient feedback without creating a status-bar layout row."""
        if source is None or not isValid(source):
            source = self.host
        QToolTip.showText(QCursor.pos(), message, source, msecShowTime=duration_ms)

    def _setting_changed(self, key, value):
        if key.startswith('floating_wall_') or key.startswith('floating_viewer_wall_') or key == 'floating_viewer_rearrange_preserve_screen_order':
            self.cancel()
        if key == 'floating_wall_manual_shortcut':
            self.manual_action.setShortcut(QKeySequence(str(value)))
        self._refresh_menus()

    def watch(self, window):
        window.installEventFilter(self)
        window.destroyed.connect(self.cancel)

    def eventFilter(self, watched, event):
        if not self._applying and self._pending is not None and event.type() in (
                QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Hide, QEvent.Type.Close):
            self.cancel()
        return False

    def cancel(self, *_):
        self._pending = None
        self.worker.cancel()

    def close(self):
        self.cancel()
        self.worker.close()

    def _options(self):
        return dict(algorithm=self.algorithm, spacing=self.host._floating_viewer_wall_gap_px(),
                    horizontal_alignment=self.host._floating_viewer_wall_horizontal_alignment())

    def plan_initial(self, ratios, bounds):
        self.last_result = pack_wall(ratios, bounds, **self._options())
        return self.last_result.rects

    def _fixed_size(self, window):
        kind = getattr(window, '_wall_size_lock_kind', None)
        if kind == 'explicit' or (kind == 'manual' and self.setting('floating_wall_preserve_manual_sizes')):
            return getattr(window, '_wall_fixed_size', None)
        return None

    def _window_payload(self, windows, bounds, *, preserve_order, reset_sizes=False):
        rects = [QRect(window.geometry()) for window in windows]
        options = self._options()
        options.update(
            preferred_sizes=None if reset_sizes else [(r.width(), r.height()) for r in rects],
            fixed_sizes=[None if reset_sizes else self._fixed_size(w) for w in windows],
            minimum_sizes=[(max(24, w.minimumWidth()), max(24, w.minimumHeight())) for w in windows],
            automatic_sizing=self.setting('floating_wall_automatic_sizing'),
            preserve_order=preserve_order, previous_rects=rects,
        )
        return [r.width() / max(1, r.height()) for r in rects], QRect(bounds), options

    def plan_existing(self, windows, bounds, *, preserve_order):
        self.cancel()
        ratios, bounds, options = self._window_payload(windows, bounds, preserve_order=preserve_order)
        self.last_result = pack_wall(ratios, bounds, **options)
        return self.last_result.rects

    def windows(self):
        return [w for w in self.host._iter_rearrangeable_floating_media_windows()
                if getattr(w, '_selection_masonry_wall_window', False) and w.isVisible()]

    def resize_finished(self, window, bypass):
        if not getattr(window, '_selection_masonry_wall_window', False):
            return
        # Keep the latest deliberate size even during manual mode / Alt bypass.
        window._wall_fixed_size = (window.width(), window.height())
        if getattr(window, '_wall_size_lock_kind', None) != 'explicit':
            window._wall_size_lock_kind = 'manual'
        if not bypass:
            self.request_reflow(window)

    def request_reflow(self, source=None, *, force=False, reset_sizes=False):
        self.cancel()
        if getattr(self.host, '_main_window_closing', False):
            return
        if not force and (self.manual_action.isChecked() or not self.setting('floating_wall_reflow_after_resize')):
            return
        windows = self.windows()
        if len(windows) < 2 or any(getattr(w, '_resize_active', False) or
                                   getattr(w, '_window_drag_active', False) for w in windows):
            return
        if self.host._floating_viewer_rearrange_preserve_screen_order():
            windows.sort(key=self.host._window_screen_order_sort_key)
        source = source if source in windows else windows[0]
        screen = QApplication.screenAt(source.geometry().center()) or source.screen()
        if screen is None:
            return
        screen_bounds = QRect(screen.availableGeometry())
        gap = self.host._floating_viewer_wall_gap_px()
        bounds = screen_bounds.adjusted(gap, gap, -gap, -gap)
        if reset_sizes:
            for window in windows:
                window._wall_fixed_size = None
                window._wall_size_lock_kind = None
        payload = self._window_payload(
            windows, bounds, preserve_order=self.host._floating_viewer_rearrange_preserve_screen_order(),
            reset_sizes=reset_sizes,
        )
        entries = [(weakref.ref(w), QRect(w.geometry())) for w in windows]
        token = self.worker.submit(_calculate, payload)
        self._pending = (token, entries, weakref.ref(screen), screen_bounds, weakref.ref(source))

    def _apply_result(self, token, result, error):
        pending = self._pending
        self._pending = None
        if pending is None or token != pending[0] or getattr(self.host, '_main_window_closing', False):
            return
        _, entries, screen_ref, screen_bounds, source_ref = pending
        screen = screen_ref()
        if screen is None or not isValid(screen) or screen.availableGeometry() != screen_bounds:
            return
        windows = []
        for reference, geometry in entries:
            window = reference()
            if (window is None or not isValid(window) or not window.isVisible()
                    or not getattr(window, '_selection_masonry_wall_window', False)
                    or window.geometry() != geometry):
                return
            windows.append(window)
        if error is not None or result is None or len(result.rects) != len(windows):
            message = ('Wall layout could not be calculated.' if error is not None else
                       'These sizes do not fit. Enable automatic sizing or release kept window sizes.')
            self.show_message(message, source_ref())
            return
        self.last_result = result
        states = [self.host._snapshot_window_arrangement_state(w) for w in windows]
        self._applying = True
        try:
            with ExitStack() as stack:
                for state in states:
                    for viewer, _ in state.get('viewer_states', []):
                        player = getattr(viewer, 'video_player', None)
                        if player is not None:
                            stack.enter_context(player.preserve_native_frame_during_geometry_update())
                for window, rect in zip(windows, result.rects):
                    window.setGeometry(rect)
                    if window.layout() is not None:
                        window.layout().activate()
                for state in states:
                    for viewer, viewer_state in state.get('viewer_states', []):
                        self.host._restore_viewer_arrangement_state(
                            viewer, viewer_state, allow_fit_restore=state.get('allow_fit_restore', True))
        finally:
            self._applying = False

    def _choose_algorithm(self, algorithm):
        self.algorithm_override = algorithm
        self.cancel()
        self._refresh_menus()
        if not self.manual_action.isChecked():
            self.request_reflow(force=True)

    def add_menu(self, menu, window=None):
        layout_menu = menu.addMenu('Wall layout')
        self._menus.append(weakref.ref(layout_menu))
        layout_menu.aboutToShow.connect(self._refresh_menus)
        layout_menu.addAction(self.manual_action)
        for label, key in (
            ('Reflow after resizing', 'floating_wall_reflow_after_resize'),
            ('Automatically size other windows', 'floating_wall_automatic_sizing'),
            ('Preserve manually resized sizes', 'floating_wall_preserve_manual_sizes'),
            ('Preserve screen order when repacking', 'floating_viewer_rearrange_preserve_screen_order'),
        ):
            action = layout_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.setting(key))
            action.setProperty('wall_setting_key', key)
            action.triggered.connect(lambda checked, k=key: settings.setValue(k, checked))
        algorithms = layout_menu.addMenu('Packing algorithm (this session)')
        algorithm_group = QActionGroup(algorithms)
        algorithm_group.setExclusive(True)
        choices = [(None, f'Use settings ({self.setting("floating_wall_algorithm")})')]
        choices.extend((name, name) for name in ALGORITHMS)
        for algorithm, label in choices:
            action = algorithms.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.algorithm_override == algorithm)
            action.setProperty('wall_algorithm', algorithm or 'settings')
            algorithm_group.addAction(action)
            if algorithm == 'MaxRects' and not maxrects_available():
                action.setEnabled(False)
                action.setToolTip('Install the project requirements to enable MaxRects.')
            action.triggered.connect(lambda checked, value=algorithm: self._choose_algorithm(value))
        layout_menu.addSeparator()
        if window is not None:
            keep = layout_menu.addAction("Keep this window's size")
            keep.setCheckable(True)
            keep.setChecked(self._fixed_size(window) is not None)
            keep.setProperty('wall_kept_window', weakref.ref(window))
            keep.triggered.connect(lambda checked: self._keep_size(window, checked))
        repack = layout_menu.addAction('Repack current wall')
        repack.triggered.connect(lambda: self.request_reflow(window, force=True))
        reset = layout_menu.addAction('Reset kept sizes and fit wall')
        reset.triggered.connect(lambda: self.request_reflow(window, force=True, reset_sizes=True))
        return layout_menu

    def _refresh_menus(self):
        live_menus = []
        for reference in self._menus:
            menu = reference()
            if menu is None or not isValid(menu):
                continue
            live_menus.append(reference)
            for action in menu.actions():
                key = action.property('wall_setting_key')
                if key:
                    action.setChecked(self.setting(key))
                window_ref = action.property('wall_kept_window')
                if window_ref is not None:
                    window = window_ref()
                    if window is not None and isValid(window):
                        action.setChecked(self._fixed_size(window) is not None)
                submenu = action.menu()
                if submenu is not None:
                    for choice in submenu.actions():
                        algorithm = choice.property('wall_algorithm')
                        if algorithm:
                            choice.setChecked(algorithm == (self.algorithm_override or 'settings'))
                            if algorithm == 'settings':
                                choice.setText(f'Use settings ({self.setting("floating_wall_algorithm")})')
        self._menus = live_menus

    def _keep_size(self, window, checked):
        self.cancel()
        window._wall_fixed_size = (window.width(), window.height()) if checked else None
        window._wall_size_lock_kind = 'explicit' if checked else None
        self._refresh_menus()
