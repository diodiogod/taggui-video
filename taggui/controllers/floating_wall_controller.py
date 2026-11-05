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
        self.auto_arrange_action = QAction('Arrange automatically after resizing', host)
        self.auto_arrange_action.setCheckable(True)
        self.auto_arrange_action.setChecked(self.automatic_layout_enabled)
        self.auto_arrange_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.auto_arrange_action.setShortcut(QKeySequence(self.setting('floating_wall_manual_shortcut')))
        self.auto_arrange_action.setToolTip('Save automatic resize arrangement on or off. Hold Alt to skip one gesture.')
        self.auto_arrange_action.toggled.connect(self._automatic_changed)
        host.addAction(self.auto_arrange_action)
        self._settings_dialog = None
        settings.change.connect(self._setting_changed)
        from controllers.wall_anchor_controller import WallAnchorController
        self.anchors = WallAnchorController(self)
        from controllers.wall_resize_preview import WallResizePreview
        self.resize_preview = WallResizePreview(self)
        from controllers.floating_resize_input import FloatingResizeInput
        self.resize_input = FloatingResizeInput(self)

    @staticmethod
    def setting(key):
        default = DEFAULT_SETTINGS[key]
        return settings.value(key, default, type=type(default))

    @property
    def algorithm(self):
        return self.algorithm_override or self.setting('floating_wall_algorithm')

    @property
    def automatic_layout_enabled(self):
        return self.setting('floating_wall_reflow_after_resize')

    def _automatic_changed(self, enabled):
        settings.setValue('floating_wall_reflow_after_resize', enabled)
        self.show_message('Automatic resize arrangement on.' if enabled else
                          'Automatic resize arrangement off. Arrange now and Ctrl-drag remain available.',
                          duration_ms=4000)

    def show_message(self, message, source=None, *, duration_ms=5000):
        """Display transient feedback without creating a status-bar layout row."""
        if source is None or not isValid(source):
            source = self.host
        QToolTip.showText(QCursor.pos(), message, source, msecShowTime=duration_ms)

    def _setting_changed(self, key, value):
        if key.startswith('floating_wall_') or key.startswith('floating_viewer_wall_') or key == 'floating_viewer_rearrange_preserve_screen_order':
            self.cancel()
        if key == 'floating_wall_manual_shortcut':
            self.auto_arrange_action.setShortcut(QKeySequence(str(value)))
        blocked = self.auto_arrange_action.blockSignals(True)
        self.auto_arrange_action.setChecked(self.automatic_layout_enabled)
        self.auto_arrange_action.blockSignals(blocked)
        self._refresh_menus()

    def watch(self, window):
        window.installEventFilter(self)
        window.destroyed.connect(self.cancel)

    def eventFilter(self, watched, event):
        preview_source = self.resize_preview.source
        if preview_source is not None and (event.type() in (QEvent.Type.Hide, QEvent.Type.Close)
                or (watched is not preview_source() and event.type() in (QEvent.Type.Move, QEvent.Type.Resize))):
            self.resize_preview.cancel()
        if event.type() == QEvent.Type.Resize and getattr(watched, '_resize_active', False):
            self.resize_preview.update(watched)
        if not self._applying and self._pending is not None and event.type() in (
                QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Hide, QEvent.Type.Close):
            self.cancel()
        return False

    def cancel(self, *_):
        if hasattr(self, "anchors"):
            self.anchors.abort()
        if hasattr(self, "resize_preview"):
            self.resize_preview.cancel()
        self._pending = None
        self.worker.cancel()

    def close(self):
        self.cancel()
        if self._settings_dialog is not None and isValid(self._settings_dialog):
            self._settings_dialog.close()
        self.worker.close()
        self.anchors.close()
        self.resize_preview.close()
        self.resize_input.close()

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
            anchored_rects=[QRect(w.geometry()) if getattr(w, "_wall_position_anchored", False) else None for w in windows],
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
        self._refresh_menus()
        if not bypass:
            self.request_reflow(window)

    def request_reflow(self, source=None, *, force=False, reset_sizes=False):
        self.cancel()
        if getattr(self.host, '_main_window_closing', False):
            return
        if not force and not self.automatic_layout_enabled:
            return
        windows = self.windows()
        if not windows or any(getattr(w, '_resize_active', False) or
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
                self.refresh_indicators(window)
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
        self.apply_rects(windows, result.rects)

    def apply_rects(self, windows, rects):
        states = [self.host._snapshot_window_arrangement_state(w) for w in windows]
        self._applying = True
        try:
            with ExitStack() as stack:
                for state in states:
                    for viewer, _ in state.get('viewer_states', []):
                        player = getattr(viewer, 'video_player', None)
                        if player is not None:
                            stack.enter_context(player.preserve_native_frame_during_geometry_update())
                for window, rect in zip(windows, rects):
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
        if self.automatic_layout_enabled:
            self.request_reflow(force=True)

    def add_menu(self, menu, window=None):
        layout_menu = menu.addMenu('Wall layout')
        # Retain Python wrappers as well as native parents. Some PySide builds
        # invalidate submenu wrappers after the last Python reference is dropped.
        if not hasattr(menu, '_wall_layout_menus'):
            menu._wall_layout_menus = []
        menu._wall_layout_menus.append(layout_menu)
        layout_menu._wall_menu_action = layout_menu.menuAction()
        layout_menu._wall_submenus = []
        self._menus.append(weakref.ref(layout_menu))
        layout_menu.aboutToShow.connect(self._refresh_menus)
        arrange = layout_menu.addAction('Arrange now')
        arrange.setToolTip('Fit the current wall while respecting window locks.')
        arrange.triggered.connect(lambda: self.request_reflow(window, force=True))
        layout_menu.addAction(self.auto_arrange_action)
        layout_menu.addSeparator()
        if window is not None:
            states = layout_menu.addMenu('This window')
            layout_menu._wall_submenus.append(states)
            group = QActionGroup(states)
            group.setExclusive(True)
            for mode, label, hint in (
                    ('flexible', 'Flexible', 'Allow this window to move and resize according to wall settings.'),
                    ('size', 'Keep size', 'Allow movement, retaining the dimensions you chose.'),
                    ('pinned', 'Pin in place', 'Keep position and size during arrangement. Ctrl-drag also pins.')):
                action = states.addAction(label)
                action.setToolTip(hint)
                action.setCheckable(True)
                action.setProperty('wall_window_mode', mode)
                action.setProperty('wall_mode_window', weakref.ref(window))
                group.addAction(action)
                action.triggered.connect(lambda checked, m=mode: self.set_window_mode(window, m))
        reset = layout_menu.addMenu('Reset layout')
        layout_menu._wall_submenus.append(reset)
        for kind, label, hint in (
                ('sizes', 'Release kept sizes', 'Release size locks; keep pinned positions. No immediate rearrangement.'),
                ('pins', 'Unpin all windows', 'Release position pins; retain separately kept sizes. No immediate rearrangement.'),
                ('all', 'Start fresh — release all locks and arrange', 'Remove all pins and size locks, then fit the wall.')):
            action = reset.addAction(label)
            action.setToolTip(hint)
            action.setProperty('wall_reset_kind', kind)
            action.triggered.connect(lambda checked, k=kind: self.reset_layout(k, window))
        layout_menu.addSeparator()
        algorithms = layout_menu.addMenu('Packing algorithm (this session)')
        layout_menu._wall_submenus.append(algorithms)
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
        layout_menu.addAction('Wall settings…', self.open_settings)
        layout_menu._wall_submenu_actions = [submenu.menuAction() for submenu in layout_menu._wall_submenus]
        self._refresh_menus()
        return layout_menu

    def _refresh_menus(self):
        for window in self.windows():
            self.refresh_indicators(window)
        live_menus = []
        for reference in self._menus:
            menu = reference()
            if menu is None or not isValid(menu):
                continue
            live_menus.append(reference)
            self._refresh_menu_actions(menu)
        self._menus = live_menus

    def _refresh_menu_actions(self, menu):
        for action in menu.actions():
            reset = action.property('wall_reset_kind')
            if reset:
                windows = self.windows()
                action.setEnabled(bool(windows) if reset == 'all' else any(
                    getattr(w, '_wall_position_anchored', False) if reset == 'pins'
                    else getattr(w, '_wall_fixed_size', None) is not None for w in windows))
            reference = action.property('wall_mode_window')
            if reference is not None:
                window = reference()
                if window is not None and isValid(window):
                    action.setChecked(action.property('wall_window_mode') == self.window_mode(window))
            algorithm = action.property('wall_algorithm')
            if algorithm:
                action.setChecked(algorithm == (self.algorithm_override or 'settings'))
                if algorithm == 'settings':
                    action.setText(f'Use settings ({self.setting("floating_wall_algorithm")})')
            if action.menu() is not None:
                self._refresh_menu_actions(action.menu())

    def window_mode(self, window):
        if getattr(window, '_wall_position_anchored', False):
            return 'pinned'
        return 'size' if self._fixed_size(window) is not None else 'flexible'

    def set_window_mode(self, window, mode):
        if mode not in ('flexible', 'size', 'pinned'):
            raise ValueError(mode)
        self.cancel()
        window._wall_position_anchored = mode == 'pinned'
        if mode != 'pinned':
            window._wall_fixed_size = (window.width(), window.height()) if mode == 'size' else None
            window._wall_size_lock_kind = 'explicit' if mode == 'size' else None
        self._refresh_menus()

    def reset_layout(self, kind, source=None):
        if kind not in ('sizes', 'pins', 'all'):
            raise ValueError(kind)
        self.cancel()
        for window in self.windows():
            if kind in ('pins', 'all'):
                window._wall_position_anchored = False
            if kind in ('sizes', 'all'):
                window._wall_fixed_size = None
                window._wall_size_lock_kind = None
        self._refresh_menus()
        if kind == 'all':
            self.request_reflow(source, force=True, reset_sizes=True)

    def open_settings(self):
        if self._settings_dialog is None or not isValid(self._settings_dialog):
            from dialogs.wall_layout_settings import WallLayoutSettingsDialog
            self._settings_dialog = WallLayoutSettingsDialog(self.host)
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    def refresh_indicators(self, window):
        from widgets.wall_constraint_indicator import WallConstraintIndicator
        enabled = self.setting('floating_wall_constraint_icons')
        pinned = bool(getattr(window, '_wall_position_anchored', False))
        kept = not pinned and self._fixed_size(window) is not None
        drag = self.anchors.drag
        preview_pin = drag is not None and (pinned or drag['source']() is window)
        offset = 14
        for attr, active, size_lock in (
                ('_wall_anchor_indicator', pinned, False),
                ('_wall_size_indicator', kept, True)):
            indicator = getattr(window, attr, None)
            if indicator is None and active and enabled:
                indicator = WallConstraintIndicator(window, size_lock=size_lock)
                if size_lock:
                    indicator.clicked.connect(lambda checked=False, w=window: self._keep_size(w, False))
                else:
                    indicator.clicked.connect(lambda checked=False, w=window: self.anchors.set_anchor(w, False))
                setattr(window, attr, indicator)
            if indicator is not None:
                indicator.move(offset, max(14, window.height() - indicator.height() - 14))
                indicator.setVisible(active and enabled and not preview_pin)
                if active and enabled:
                    indicator.raise_()
            if active:
                offset += 22

    def _keep_size(self, window, checked):
        self.cancel()
        window._wall_fixed_size = (window.width(), window.height()) if checked else None
        window._wall_size_lock_kind = 'explicit' if checked else None
        self.refresh_indicators(window)
        self._refresh_menus()
