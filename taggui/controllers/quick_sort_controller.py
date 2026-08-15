"""Focused keyboard-driven Quick Sort session orchestration."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
import json
import os
from pathlib import Path
import time
from typing import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QItemSelectionModel,
    QRunnable,
    QThreadPool,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDockWidget,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from utils.quick_sort import (
    QuickSortMapping,
    QuickSortProfile,
    QuickSortSessionStore,
    QuickSortValidationError,
    normalize_key_sequence,
)
from utils.quick_sort_file_service import (
    QuickSortCollisionError,
    QuickSortFileOperation,
    QuickSortFileResult,
    QuickSortFileService,
)


@dataclass(frozen=True)
class QuickSortQueueSnapshot:
    """Immutable path or database-ID queue captured when a session starts."""

    paths: tuple[Path, ...] = ()
    image_ids: tuple[int, ...] = ()
    directory_path: Path | None = None
    database: object | None = None

    def __len__(self) -> int:
        return len(self.paths) if self.paths else len(self.image_ids)

    def path_at(self, index: int) -> Path | None:
        if index < 0 or index >= len(self):
            return None
        if self.paths:
            return Path(self.paths[index])
        if self.database is None or self.directory_path is None:
            return None
        row = self.database.get_image_by_id(int(self.image_ids[index]))
        if not row:
            return None
        relative_path = str(row.get("file_name") or "").strip()
        if not relative_path:
            return None
        return Path(self.directory_path) / relative_path


@dataclass
class QuickSortHistoryRecord:
    index: int
    label: str
    color: str
    destination_id: str | None = None
    qualifier_id: str | None = None
    operation: QuickSortFileOperation | None = None
    skipped: bool = False
    source_path: str | None = None
    source_size: int | None = None
    source_mtime_ns: int | None = None
    source_image_id: int | None = None


class _WorkerSignals(QObject):
    finished = Signal(object, object)


class _QuickSortWorker(QRunnable):
    def __init__(self, callback: Callable[[], object]):
        super().__init__()
        self.callback = callback
        self.signals = _WorkerSignals()

    def run(self):
        try:
            result = self.callback()
        except Exception as exc:  # noqa: BLE001 - delivered to the UI thread
            self.signals.finished.emit(None, exc)
        else:
            self.signals.finished.emit(result, None)


class QuickSortHud(QObject):
    """Small corner overlays that keep the media unobstructed while sorting."""

    exit_requested = Signal()
    fit_requested = Signal()
    original_size_requested = Signal()
    start_fresh_requested = Signal()

    def __init__(self, viewport: QWidget):
        super().__init__(viewport)
        self.viewport = viewport
        self.viewport.installEventFilter(self)

        self.status_bar = QFrame(viewport)
        self.status_bar.setObjectName("quickSortStatusBar")
        status_layout = QHBoxLayout(self.status_bar)
        status_layout.setContentsMargins(12, 7, 7, 7)
        status_layout.setSpacing(10)
        self.title_label = QLabel()
        self.title_label.setObjectName("quickSortHudTitle")
        self.stage_label = QLabel("Choose a destination")
        self.stage_label.setObjectName("quickSortHudStage")
        self.stage_label.setTextFormat(Qt.TextFormat.PlainText)
        self.stage_label.setWordWrap(True)
        self.stage_label.setMinimumWidth(0)
        self.progress_label = QLabel("0 / 0")
        self.progress_label.setObjectName("quickSortHudProgress")
        self.progress_label.setTextFormat(Qt.TextFormat.PlainText)
        self.fit_button = QPushButton("Fit")
        self.fit_button.setObjectName("quickSortViewButton")
        self.fit_button.setToolTip("Fit the whole image in the viewer")
        self.fit_button.clicked.connect(self.fit_requested.emit)
        self.original_button = QPushButton("1:1")
        self.original_button.setObjectName("quickSortViewButton")
        self.original_button.setToolTip(
            "Show original pixel size without enlarging the image"
        )
        self.original_button.clicked.connect(self.original_size_requested.emit)
        self.exit_button = QPushButton("×")
        self.exit_button.setObjectName("quickSortExitButton")
        self.exit_button.setToolTip("Exit Quick Sort (Esc when no qualifier is pending)")
        self.exit_button.setFixedSize(24, 24)
        self.exit_button.clicked.connect(self.exit_requested)
        status_layout.addWidget(self.progress_label)
        status_layout.addWidget(self.stage_label, 1)
        status_layout.addWidget(self.fit_button)
        status_layout.addWidget(self.original_button)
        status_layout.addWidget(self.exit_button)
        self._status_layout = status_layout

        self.legend = QFrame(viewport)
        self.legend.setObjectName("quickSortLegend")
        legend_layout = QHBoxLayout(self.legend)
        legend_layout.setContentsMargins(12, 8, 12, 8)
        self.legend_label = QLabel()
        self.legend_label.setObjectName("quickSortLegendText")
        self.legend_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.legend_label.setTextFormat(Qt.TextFormat.RichText)
        self.legend_label.setWordWrap(True)
        self.legend_label.setMinimumWidth(0)
        legend_layout.addWidget(self.legend_label)

        self.feedback = QFrame(viewport)
        self.feedback.setObjectName("quickSortFeedback")
        feedback_layout = QVBoxLayout(self.feedback)
        feedback_layout.setContentsMargins(12, 8, 12, 8)
        self.feedback_title = QLabel()
        self.feedback_title.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.feedback_title.setObjectName("quickSortFeedbackTitle")
        self.feedback_title.setTextFormat(Qt.TextFormat.PlainText)
        self.feedback_title.setWordWrap(True)
        self.feedback_title.setMinimumWidth(0)
        self.feedback_detail = QLabel()
        self.feedback_detail.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.feedback_detail.setObjectName("quickSortFeedbackDetail")
        self.feedback_detail.setTextFormat(Qt.TextFormat.PlainText)
        self.feedback_detail.setWordWrap(True)
        self.feedback_detail.setMinimumWidth(0)
        self.feedback_action = QPushButton("Start fresh")
        self.feedback_action.setObjectName("quickSortFeedbackAction")
        self.feedback_action.setToolTip(
            "Clear this completed review and begin the current dataset again"
        )
        self.feedback_action.clicked.connect(self.start_fresh_requested.emit)
        self.feedback_action.hide()
        feedback_layout.addWidget(self.feedback_title)
        feedback_layout.addWidget(self.feedback_detail)
        feedback_layout.addWidget(
            self.feedback_action,
            0,
            Qt.AlignmentFlag.AlignRight,
        )
        self.feedback.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )
        self.feedback_effect = QGraphicsOpacityEffect(self.feedback)
        self.feedback.setGraphicsEffect(self.feedback_effect)
        self.feedback_animation = QPropertyAnimation(
            self.feedback_effect,
            b"opacity",
            self,
        )
        self.feedback_animation.setDuration(1900)
        self.feedback_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.feedback_animation.setKeyValueAt(0.0, 0.0)
        self.feedback_animation.setKeyValueAt(0.08, 1.0)
        self.feedback_animation.setKeyValueAt(0.76, 1.0)
        self.feedback_animation.setKeyValueAt(1.0, 0.0)
        self.feedback_animation.finished.connect(self.feedback.hide)

        self._apply_style("#62E7D8")
        self._legend_mapping_count = 0
        self.hide()

    def _apply_style(self, accent: str):
        color = QColor(accent)
        if not color.isValid():
            color = QColor("#62E7D8")
        accent = color.name()
        style = f"""
            QFrame#quickSortStatusBar, QFrame#quickSortLegend {{
                background: rgba(28, 28, 28, 150);
                border: 1px solid rgba(112, 112, 112, 105);
                border-radius: 6px;
            }}
            QLabel#quickSortHudStage {{ color: #F0F0F0; font-weight: 600; }}
            QLabel#quickSortHudProgress {{ color: #BDBDBD; font-weight: 600; }}
            QLabel#quickSortLegendText {{ color: #D5D5D5; font-size: 11px; }}
            QPushButton#quickSortExitButton {{
                color: #E8E8E8; background: rgba(60, 60, 60, 150);
                border: 1px solid rgba(130, 130, 130, 120);
                border-radius: 5px; padding: 0; font-weight: 800;
            }}
            QPushButton#quickSortExitButton:hover {{ background: rgba(95, 95, 95, 210); }}
            QPushButton#quickSortViewButton {{
                color: #E0E0E0; background: rgba(55, 55, 55, 145);
                border: 1px solid rgba(120, 120, 120, 110);
                border-radius: 5px; padding: 3px 6px; font-weight: 600;
            }}
            QPushButton#quickSortViewButton:hover {{ background: rgba(85, 85, 85, 205); }}
            QFrame#quickSortFeedback {{
                background: rgba(28, 28, 28, 220);
                border: 2px solid {accent}; border-radius: 8px;
            }}
            QLabel#quickSortFeedbackTitle {{ color: {accent}; font-size: 16px; font-weight: 850; }}
            QLabel#quickSortFeedbackDetail {{ color: #F0F0F0; font-size: 11px; font-weight: 650; }}
            QPushButton#quickSortFeedbackAction {{
                color: #161616; background: {accent}; border: 0;
                border-radius: 5px; padding: 5px 12px; font-weight: 750;
            }}
            QPushButton#quickSortFeedbackAction:hover {{ background: {color.lighter(112).name()}; }}
        """
        self.status_bar.setStyleSheet(style)
        self.legend.setStyleSheet(style)
        self.feedback.setStyleSheet(style)

    def eventFilter(self, watched, event):
        viewport = getattr(self, "viewport", None)
        if viewport is not None and watched is viewport and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Show,
        }:
            QTimer.singleShot(0, self.reposition)
        return False

    def reposition(self):
        if not self.status_bar.isVisible():
            return
        bounds = self.viewport.rect()
        if bounds.width() <= 0 or bounds.height() <= 0:
            return
        margin = max(0, min(14, (bounds.width() - 1) // 12))
        available_width = max(1, bounds.width() - margin * 2)

        narrow = available_width < 360
        self.title_label.hide()
        self.progress_label.setVisible(available_width >= 180)
        self._status_layout.setContentsMargins(
            7 if narrow else 12,
            6 if narrow else 7,
            6 if narrow else 7,
            6 if narrow else 7,
        )
        self._status_layout.setSpacing(5 if narrow else 10)
        self.status_bar.setMinimumWidth(0)
        status_width = min(available_width, 460)
        self.stage_label.setMaximumWidth(max(80, status_width - 190))
        self.status_bar.setMaximumWidth(status_width)
        self.status_bar.resize(status_width, self.status_bar.sizeHint().height())
        self.status_bar.adjustSize()
        status_height = min(bounds.height(), self.status_bar.sizeHint().height())
        self.status_bar.setGeometry(
            margin,
            margin,
            status_width,
            status_height,
        )

        # Use extra horizontal space for larger mapping sets so every named
        # override remains visible without turning the legend into a tall list.
        preferred_legend_width = min(
            720,
            max(300, 120 * min(6, max(1, self._legend_mapping_count))),
        )
        legend_width = min(available_width, preferred_legend_width)
        legend_content_width = max(1, legend_width - 24)
        self.legend_label.setMaximumWidth(legend_content_width)
        self.legend.setMinimumWidth(0)
        self.legend.setMaximumWidth(legend_width)
        self.legend.resize(legend_width, self.legend.sizeHint().height())
        self.legend.adjustSize()
        maximum_legend_height = max(1, bounds.height() - margin * 2 - status_height)
        legend_height = min(maximum_legend_height, self.legend.sizeHint().height())
        self.legend.setGeometry(
            margin,
            max(margin, bounds.height() - legend_height - margin),
            legend_width,
            legend_height,
        )

        feedback_width_limit = min(available_width, 340)
        feedback_content_width = max(1, feedback_width_limit - 24)
        self.feedback_title.setMaximumWidth(feedback_content_width)
        self.feedback_detail.setMaximumWidth(feedback_content_width)
        self.feedback.setMinimumWidth(0)
        self.feedback.setMaximumWidth(feedback_width_limit)
        self.feedback.resize(feedback_width_limit, self.feedback.sizeHint().height())
        self.feedback.adjustSize()
        feedback_size = self.feedback.sizeHint()
        feedback_width = min(feedback_width_limit, feedback_size.width())
        feedback_height = min(bounds.height(), feedback_size.height())
        self.feedback.setGeometry(
            max(margin, bounds.width() - feedback_width - margin),
            max(margin, bounds.height() - feedback_height - margin),
            feedback_width,
            feedback_height,
        )
        self.raise_()

    def raise_(self):
        self.status_bar.raise_()
        self.legend.raise_()
        self.feedback.raise_()

    def show(self):
        self.status_bar.show()
        self.legend.show()
        self.reposition()

    def hide(self):
        self.feedback_animation.stop()
        self.feedback_action.hide()
        self.status_bar.hide()
        self.legend.hide()
        self.feedback.hide()

    def set_state(
        self,
        *,
        stage: str,
        progress: str,
        mappings: list[QuickSortMapping],
        standard_keys: bool = False,
        control_text: str | None = None,
    ):
        self.stage_label.setText(stage)
        self.progress_label.setText(progress)
        viewport_width = max(1, self.viewport.width())
        self._legend_mapping_count = len(mappings)
        items = [
            f'<span style="color:{mapping.color};font-weight:900">'
            f'[{html.escape(mapping.key)}]</span> {html.escape(mapping.name)}'
            for mapping in mappings
        ]
        legend_target_width = min(viewport_width - 28, 696)
        per_row = max(1, min(6, legend_target_width // 115))
        rows = [
            " &nbsp;·&nbsp; ".join(items[index:index + per_row])
            for index in range(0, len(items), per_row)
        ]
        legend = "<br>".join(rows)
        if standard_keys:
            automatic = (
                '<span style="color:#7AA2FF;font-weight:700">'
                'A-Z / 0-9 → matching folders</span>'
            )
            legend = f"{automatic}<br>{legend}" if legend else automatic
        controls = control_text or (
            '<span style="color:#A0A0A0;font-size:10px">'
            'Space skip &nbsp;·&nbsp; Ctrl+Z undo &nbsp;·&nbsp; '
            'F11 fullscreen &nbsp;·&nbsp; Esc exit</span>'
        )
        legend = f"{legend}<br>{controls}" if legend else controls
        self.legend_label.setText(legend or "No active mappings")
        self.reposition()

    def show_feedback(
        self,
        title: str,
        detail: str,
        color: str,
        *,
        action_text: str | None = None,
        persistent: bool = False,
    ):
        self._apply_style(color)
        self.feedback_title.setText(title)
        self.feedback_detail.setText(detail)
        self.feedback_action.setVisible(bool(action_text))
        if action_text:
            self.feedback_action.setText(action_text)
        self.feedback.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            not bool(action_text),
        )
        self.feedback.adjustSize()
        self.feedback.show()
        self.reposition()
        self.feedback_animation.stop()
        if persistent:
            self.feedback_effect.setOpacity(1.0)
        else:
            self.feedback_effect.setOpacity(0.0)
            self.feedback_animation.start()


class QuickSortController(QObject):
    """Own a fixed Quick Sort queue, focused layout, and reversible operations."""

    active_changed = Signal(bool)
    progress_changed = Signal(str)
    session_finished = Signal(dict)

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.file_service = QuickSortFileService()
        self.session_store = QuickSortSessionStore()
        self.thread_pool = QThreadPool.globalInstance()
        self._workers: set[_QuickSortWorker] = set()
        self.hud = QuickSortHud(main_window.image_viewer.view.viewport())
        main_window.image_viewer._quick_sort_hud = self.hud
        self.hud.exit_requested.connect(self.finish_session)
        self.hud.start_fresh_requested.connect(self.restart_fresh_session)
        zoom_fit = getattr(main_window.image_viewer, "zoom_fit", None)
        if callable(zoom_fit):
            self.hud.fit_requested.connect(zoom_fit)
        zoom_original = getattr(main_window.image_viewer, "zoom_original", None)
        if callable(zoom_original):
            self.hud.original_size_requested.connect(zoom_original)
        self.profile: QuickSortProfile | None = None
        self.queue: QuickSortQueueSnapshot | None = None
        self.position = 0
        self.pending_qualifier_id: str | None = None
        self.history: list[QuickSortHistoryRecord] = []
        self.history_cursor = 0
        self._decisions: dict[int, QuickSortHistoryRecord] = {}
        self.busy = False
        self.active = False
        self._session_token = 0
        self._saved_layout: dict | None = None
        self._browser_context: dict | None = None
        self._coordinated_browser_contexts: list[dict] = []
        self._missing_indices: set[int] = set()
        self._finish_when_idle = False
        self._resume_session_key: str | None = None

    @staticmethod
    def key_sequence_from_event(event) -> str:
        try:
            text = QKeySequence(event.keyCombination()).toString(
                QKeySequence.SequenceFormat.PortableText
            )
        except Exception:
            text = ""
        if not text:
            try:
                text = str(event.text() or "")
            except Exception:
                text = ""
        return normalize_key_sequence(text)

    @staticmethod
    def _absolute_path(path: Path | str) -> Path:
        """Return a normalized absolute path without dereferencing symlinks."""
        expanded = Path(path).expanduser()
        return Path(os.path.abspath(os.fspath(expanded)))

    @classmethod
    def _relative_to_root(cls, path: Path | str, root: Path | str) -> Path | None:
        candidate = cls._absolute_path(path)
        absolute_root = cls._absolute_path(root)
        try:
            return candidate.relative_to(absolute_root)
        except ValueError:
            return None

    @classmethod
    def _paths_overlap(cls, first: Path | str, second: Path | str) -> bool:
        return (
            cls._relative_to_root(first, second) is not None
            or cls._relative_to_root(second, first) is not None
        )

    @classmethod
    def _context_root(cls, context: dict) -> Path | None:
        model = context.get("model")
        root = getattr(model, "_directory_path", None)
        return cls._absolute_path(root) if root is not None else None

    def _loaded_browser_contexts(self) -> list[dict]:
        main = self.main_window
        contexts = [
            {
                "name": "primary",
                "model": main.image_list_model,
                "proxy": main.proxy_image_list_model,
                "image_list": main.image_list,
                "owner": main,
            }
        ]
        secondary = getattr(main, "_secondary_browser", None)
        if secondary is not None:
            contexts.append(
                {
                    "name": "secondary",
                    "model": secondary.image_list_model,
                    "proxy": secondary.proxy_image_list_model,
                    "image_list": secondary.dock,
                    "owner": secondary,
                }
            )
        return [context for context in contexts if self._context_root(context) is not None]

    @staticmethod
    def _dedupe_contexts(contexts: list[dict]) -> list[dict]:
        unique: list[dict] = []
        seen_models: set[int] = set()
        for context in contexts:
            model_id = id(context.get("model"))
            if model_id in seen_models:
                continue
            seen_models.add(model_id)
            unique.append(context)
        return unique

    def _contexts_overlapping_paths(self, paths: list[Path]) -> list[dict]:
        candidates = [self._absolute_path(path) for path in paths if path is not None]
        affected = []
        for context in self._loaded_browser_contexts():
            root = self._context_root(context)
            if root is not None and any(
                self._paths_overlap(root, candidate) for candidate in candidates
            ):
                affected.append(context)
        return affected

    def _profile_route_roots(
        self,
        profile: QuickSortProfile,
        queue: QuickSortQueueSnapshot,
    ) -> list[Path]:
        fallback = (
            self._absolute_path(queue.directory_path)
            if queue.directory_path
            else None
        )
        qualifiers: list[QuickSortMapping | None]
        if not profile.qualifier_enabled:
            qualifiers = [None]
        else:
            qualifiers = list(profile.enabled_qualifiers())
            if profile.missing_qualifier == "unclassified":
                qualifiers.append(None)
        roots: list[Path] = []
        base_root = (
            self._absolute_path(Path(profile.base_destination).expanduser())
            if profile.base_destination.strip()
            else fallback
        )
        if base_root is not None:
            # Automatic A-Z / 0-9 routes are created lazily, so the common
            # parent is the only complete destination domain known at start.
            roots.append(base_root)
        for destination in profile.enabled_destinations():
            for qualifier in qualifiers:
                try:
                    roots.append(
                        self._absolute_path(
                            profile.route_directory(
                                destination,
                                qualifier,
                                fallback_base=fallback,
                            )
                        )
                    )
                except QuickSortValidationError:
                    continue
        return roots

    @staticmethod
    def _cancel_context_validation(contexts: list[dict]):
        for context in contexts:
            cancel_validation = getattr(
                context.get("model"),
                "cancel_background_path_validation",
                None,
            )
            if callable(cancel_validation):
                cancel_validation()

    @staticmethod
    def _append_sql(base_sql: str, clause: str) -> str:
        base = str(base_sql or "").strip()
        return f"({base}) AND ({clause})" if base else clause

    def resolve_browser_context(self) -> dict:
        """Return the browser that currently owns the user's working context."""
        if self.active and self._browser_context is not None:
            return self._browser_context
        main = self.main_window
        manager = getattr(main, "_context_switch_manager", None)
        secondary = getattr(main, "_secondary_browser", None)
        if (
            manager is not None
            and getattr(manager, "active_context", "primary") == "secondary"
            and secondary is not None
            and not secondary.dock.isHidden()
        ):
            return {
                "name": "secondary",
                "model": secondary.image_list_model,
                "proxy": secondary.proxy_image_list_model,
                "image_list": secondary.dock,
                "owner": secondary,
            }
        return {
            "name": "primary",
            "model": main.image_list_model,
            "proxy": main.proxy_image_list_model,
            "image_list": main.image_list,
            "owner": main,
        }

    def _paginated_batch_for_profile(
        self,
        profile: QuickSortProfile,
        *,
        model,
        image_list,
    ):
        if profile.source_scope == "selected":
            batch = image_list.get_selected_image_batch()
            if batch is None or not hasattr(batch, "snapshot_ids"):
                return None
            filter_sql = str(batch.filter_sql or "")
            if not profile.include_videos:
                filter_sql = self._append_sql(filter_sql, "is_video = 0")
            return model.create_paginated_image_batch(
                selection_mode=str(batch.selection_mode),
                selection_paths=tuple(batch.selection_paths),
                filter_sql=filter_sql,
                filter_bindings=tuple(batch.filter_bindings),
            )

        if profile.source_scope == "filtered":
            filter_sql = str(getattr(model, "_filter_sql", "") or "")
            bindings = tuple(getattr(model, "_filter_bindings", ()) or ())
        else:
            filter_sql = str(getattr(model, "_scope_sql", "") or "")
            bindings = tuple(getattr(model, "_scope_bindings", ()) or ())
        if profile.source_scope == "current_folder" and not profile.include_subfolders:
            filter_sql = self._append_sql(
                filter_sql,
                "instr(replace(file_name, '\\', '/'), '/') = 0",
            )
        if not profile.include_videos:
            filter_sql = self._append_sql(filter_sql, "is_video = 0")
        return model.create_paginated_image_batch(
            filter_sql=filter_sql,
            filter_bindings=bindings,
        )

    def build_queue(
        self,
        profile: QuickSortProfile,
        context: dict | None = None,
    ) -> QuickSortQueueSnapshot:
        context = context or self.resolve_browser_context()
        model = context["model"]
        image_list = context["image_list"]
        proxy = context["proxy"]
        directory = getattr(model, "_directory_path", None)
        if directory is None:
            raise QuickSortValidationError("Load a folder before starting Quick Sort.")
        if getattr(model, "_paginated_mode", False):
            batch = self._paginated_batch_for_profile(
                profile,
                model=model,
                image_list=image_list,
            )
            if batch is None:
                raise QuickSortValidationError(
                    "No images are selected for this Quick Sort scope."
                )
            image_ids = tuple(batch.snapshot_ids())
            return QuickSortQueueSnapshot(
                image_ids=image_ids,
                directory_path=self._absolute_path(directory),
                database=getattr(model, "_db", None),
            )

        if profile.source_scope == "selected":
            images = image_list.list_view.get_selected_images()
        elif profile.source_scope == "filtered":
            images = [
                proxy.index(row, 0).data(Qt.ItemDataRole.UserRole)
                for row in range(proxy.rowCount())
            ]
        else:
            images = list(model.iter_all_images())
        root = self._absolute_path(directory)
        paths: list[Path] = []
        seen: set[str] = set()
        for image in images:
            if image is None or not getattr(image, "path", None):
                continue
            if not profile.include_videos and bool(getattr(image, "is_video", False)):
                continue
            path = self._absolute_path(image.path)
            if (
                profile.source_scope == "current_folder"
                and not profile.include_subfolders
                and path.parent != root
            ):
                continue
            key = os.path.normcase(str(path))
            if key in seen:
                continue
            seen.add(key)
            paths.append(path)
        return QuickSortQueueSnapshot(paths=tuple(paths), directory_path=root)

    def estimate_queue_count(
        self,
        profile: QuickSortProfile,
        context: dict | None = None,
    ) -> int:
        """Count the eligible immutable queue without materializing media."""
        context = context or self.resolve_browser_context()
        model = context["model"]
        if getattr(model, "_paginated_mode", False):
            batch = self._paginated_batch_for_profile(
                profile,
                model=model,
                image_list=context["image_list"],
            )
            # Counting must stay O(1) for million-item datasets. Materializing
            # snapshot_ids here made a setup-panel label perform the full
            # queue query before the user even pressed Start.
            return int(getattr(batch, "count", 0) or 0) if batch is not None else 0
        return len(self.build_queue(profile, context))

    def start_session(self, profile: QuickSortProfile) -> bool:
        if self.active or self.busy:
            return False
        try:
            profile.validate()
            browser_context = self.resolve_browser_context()
            queue = self.build_queue(profile, browser_context)
        except QuickSortValidationError as exc:
            QMessageBox.warning(self.main_window, "Quick Sort", str(exc))
            return False
        except Exception as exc:  # database-backed snapshots can fail independently
            QMessageBox.warning(
                self.main_window,
                "Quick Sort",
                f"Could not create the Quick Sort queue:\n\n{exc}",
            )
            return False
        if len(queue) == 0:
            QMessageBox.information(
                self.main_window,
                "Quick Sort",
                "No media is available in the selected scope.",
            )
            return False
        self.profile = profile
        self.queue = queue
        self._browser_context = browser_context
        affected_paths: list[Path] = []
        if queue.directory_path is not None:
            affected_paths.append(self._absolute_path(queue.directory_path))
        affected_paths.extend(self._profile_route_roots(profile, queue))
        self._coordinated_browser_contexts = self._dedupe_contexts(
            [browser_context, *self._contexts_overlapping_paths(affected_paths)]
        )
        self._cancel_context_validation(self._coordinated_browser_contexts)
        self.position = 0
        self.pending_qualifier_id = None
        self.history.clear()
        self.history_cursor = 0
        self._decisions.clear()
        self._missing_indices.clear()
        self._resume_session_key = self._session_key(
            profile,
            queue.directory_path,
        )
        self._restore_session_state()
        self._finish_when_idle = False
        self._session_token += 1
        self.active = True
        try:
            self._enter_focused_layout()
            self.hud.show()
            self._show_current()
        except Exception as exc:
            self.hud.hide()
            reload_contexts = list(self._coordinated_browser_contexts)
            try:
                self._restore_layout()
            except Exception:
                pass
            self.active = False
            self.profile = None
            self.queue = None
            self._resume_session_key = None
            self._browser_context = None
            self._coordinated_browser_contexts.clear()
            QTimer.singleShot(
                0,
                lambda contexts=reload_contexts, active=browser_context: self._reload_browsers(
                    contexts,
                    active,
                ),
            )
            QMessageBox.warning(
                self.main_window,
                "Quick Sort",
                f"Could not enter Quick Sort mode:\n\n{exc}",
            )
            return False
        self.active_changed.emit(True)
        return True

    def _enter_focused_layout(self):
        main = self.main_window
        context = self._browser_context or self.resolve_browser_context()
        image_list = context["image_list"]
        menu_widget = main.menuWidget()
        self._saved_layout = {
            "window_state": main.saveState(),
            "main_viewer_visible": bool(getattr(main, "_main_viewer_visible", True)),
            "viewer_fullscreen": bool(
                main._viewer_is_fullscreen(main.image_viewer)
            ),
            "menu_visible": bool(menu_widget is not None and menu_widget.isVisible()),
            "filter_text": str(image_list.filter_line_edit.text() or ""),
            "media_type": str(image_list.media_type_combo_box.currentText() or "All"),
        }
        # The immutable queue already captured the requested domain. Remove live
        # filters so every queued path can be resolved into the shared viewer.
        image_list.filter_line_edit.clear()
        image_list.media_type_combo_box.setCurrentText("All")
        self._apply_browser_filter()
        main.set_main_viewer_visible(True, save=False)
        for dock in main.findChildren(QDockWidget):
            dock.hide()
        for toolbar in main.findChildren(QToolBar):
            toolbar.hide()
        if menu_widget is not None:
            menu_widget.hide()
        if self.profile is not None and self.profile.start_fullscreen:
            main._enter_viewer_fullscreen(main.image_viewer)
        QTimer.singleShot(0, self.hud.reposition)

    def _restore_layout(self):
        main = self.main_window
        context = self._browser_context or self.resolve_browser_context()
        image_list = context["image_list"]
        saved = self._saved_layout or {}
        was_fullscreen = bool(saved.get("viewer_fullscreen", False))
        is_fullscreen = bool(main._viewer_is_fullscreen(main.image_viewer))
        if is_fullscreen and not was_fullscreen:
            main._restore_fullscreen_viewer(main.image_viewer, close_window=True)
        state = saved.get("window_state")
        if state is not None:
            main.restoreState(state)
            main._preserve_restored_dock_layout_until = time.time() + 2.0
        main.set_main_viewer_visible(
            bool(saved.get("main_viewer_visible", True)),
            save=False,
        )
        menu_widget = main.menuWidget()
        if menu_widget is not None:
            menu_widget.setVisible(bool(saved.get("menu_visible", True)))
        image_list.media_type_combo_box.setCurrentText(
            str(saved.get("media_type") or "All")
        )
        image_list.filter_line_edit.setText(str(saved.get("filter_text") or ""))
        self._apply_browser_filter()
        if was_fullscreen and not main._viewer_is_fullscreen(main.image_viewer):
            main._enter_viewer_fullscreen(main.image_viewer)
        self._saved_layout = None

    def _apply_browser_filter(self):
        context = self._browser_context or self.resolve_browser_context()
        if context.get("name") == "secondary":
            apply_now = getattr(context.get("owner"), "_apply_filter_now", None)
            if callable(apply_now):
                apply_now()
            return
        self.main_window.apply_image_list_filter_now()

    def _qualifier_by_id(self, mapping_id: str | None) -> QuickSortMapping | None:
        if self.profile is None or not mapping_id:
            return None
        return next(
            (
                mapping
                for mapping in self.profile.enabled_qualifiers()
                if mapping.id == mapping_id
            ),
            None,
        )

    def _decision_at(self, index: int) -> QuickSortHistoryRecord | None:
        return self._decisions.get(int(index))

    def _session_key(
        self,
        profile: QuickSortProfile,
        directory_path: Path | str | None,
    ) -> str:
        root = self._absolute_path(directory_path) if directory_path else Path()
        identity = json.dumps(
            [
                profile.id,
                os.path.normcase(str(root)).casefold(),
                profile.source_scope,
                bool(profile.include_subfolders),
                bool(profile.include_videos),
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def _record_source_identity(self, index: int) -> dict:
        if self.queue is None:
            return {}
        path = self.queue.path_at(index)
        if path is None:
            return {}
        values = {"source_path": str(self._absolute_path(path))}
        try:
            path_stat = os.lstat(path)
        except OSError:
            path_stat = None
        if path_stat is not None:
            values["source_size"] = int(path_stat.st_size)
            values["source_mtime_ns"] = int(path_stat.st_mtime_ns)
        if self.queue.image_ids and 0 <= index < len(self.queue.image_ids):
            values["source_image_id"] = int(self.queue.image_ids[index])
        return values

    def _persist_session_state(self) -> None:
        if not self._resume_session_key or self.queue is None or self.profile is None:
            return
        items = []
        for index, record in sorted(self._decisions.items()):
            source_path = record.source_path
            if not source_path:
                path = self.queue.path_at(index)
                source_path = str(self._absolute_path(path)) if path is not None else None
            if not source_path:
                continue
            items.append(
                {
                    "path": source_path,
                    "state": "skipped" if record.skipped else "sorted",
                    "size": record.source_size,
                    "mtime_ns": record.source_mtime_ns,
                    "image_id": record.source_image_id,
                }
            )
        try:
            if items:
                self.session_store.put(
                    self._resume_session_key,
                    {
                        "profile_id": self.profile.id,
                        "directory_path": str(self.queue.directory_path or ""),
                        "items": items,
                    },
                )
            else:
                self.session_store.remove(self._resume_session_key)
        except OSError:
            pass

    def _restore_session_state(self) -> None:
        if not self._resume_session_key or self.queue is None:
            return
        state = self.session_store.get(self._resume_session_key)
        raw_items = state.get("items", []) if state else []
        if not isinstance(raw_items, list):
            return
        if self.queue.image_ids:
            wanted_ids = {
                int(item["image_id"])
                for item in raw_items
                if isinstance(item, dict) and item.get("image_id") is not None
            }
            positions = {
                int(image_id): index
                for index, image_id in enumerate(self.queue.image_ids)
                if int(image_id) in wanted_ids
            }
        else:
            positions = {
                os.path.normcase(str(self._absolute_path(path))).casefold(): index
                for index, path in enumerate(self.queue.paths)
            }
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            saved_path = str(item.get("path") or "")
            image_id = item.get("image_id")
            if self.queue.image_ids and image_id is not None:
                index = positions.get(int(image_id))
            else:
                index = positions.get(
                    os.path.normcase(str(self._absolute_path(saved_path))).casefold()
                )
            if index is None:
                continue
            current_path = self.queue.path_at(index)
            if current_path is None or not current_path.exists():
                continue
            try:
                current_stat = os.lstat(current_path)
            except OSError:
                continue
            saved_size = item.get("size")
            saved_mtime = item.get("mtime_ns")
            if saved_size is not None and int(saved_size) != int(current_stat.st_size):
                continue
            if saved_mtime is not None and int(saved_mtime) != int(current_stat.st_mtime_ns):
                continue
            skipped = str(item.get("state") or "") == "skipped"
            self._decisions[index] = QuickSortHistoryRecord(
                index=index,
                label="Remembered skip" if skipped else "Remembered sort",
                color="#93A5B4",
                skipped=skipped,
                source_path=str(self._absolute_path(current_path)),
                source_size=int(current_stat.st_size),
                source_mtime_ns=int(current_stat.st_mtime_ns),
                source_image_id=int(image_id) if image_id is not None else None,
            )

    def clear_saved_session(self, profile: QuickSortProfile) -> bool:
        context = self.resolve_browser_context()
        directory = getattr(context.get("model"), "_directory_path", None)
        if directory is None:
            return False
        try:
            self.session_store.remove(self._session_key(profile, directory))
        except OSError:
            return False
        return True

    def restart_fresh_session(self):
        """Clear a completed run and immediately begin the same scope again."""
        if not self.active or self.busy or self.profile is None:
            return
        profile = self.profile
        session_key = self._resume_session_key
        try:
            if session_key:
                self.session_store.remove(session_key)
        except OSError as exc:
            self.hud.show_feedback(
                "COULD NOT START FRESH",
                str(exc),
                "#E87979",
            )
            return
        self.finish_session()
        QTimer.singleShot(0, lambda saved_profile=profile: self.start_session(saved_profile))

    def _route_count(self, destination_id: str, qualifier_id: str | None) -> int:
        return sum(
            1
            for record in self._decisions.values()
            if not record.skipped
            and record.destination_id == destination_id
            and record.qualifier_id == qualifier_id
        )

    def _skip_count(self) -> int:
        return sum(1 for record in self._decisions.values() if record.skipped)

    def _progress_text(self) -> str:
        total = len(self.queue) if self.queue is not None else 0
        resolved = len(self._decisions) + len(self._missing_indices)
        current = min(total, resolved + 1) if resolved < total else total
        return f"{current:,} / {total:,}"

    def _update_hud(self):
        if not self.active or self.profile is None:
            return
        qualifier = self._qualifier_by_id(self.pending_qualifier_id)
        if qualifier is not None:
            stage = f"{qualifier.name.upper()} selected · Choose a destination"
            mappings = self.profile.enabled_destinations()
        elif self.profile.qualifier_enabled:
            if self.profile.missing_qualifier == "unclassified":
                stage = (
                    f"Choose {self.profile.qualifier_name.lower()} or a destination "
                    "(unclassified)"
                )
                mappings = [
                    *self.profile.enabled_qualifiers(),
                    *self.profile.enabled_destinations(),
                ]
            else:
                stage = f"Choose {self.profile.qualifier_name.lower()} first"
                mappings = self.profile.enabled_qualifiers()
        else:
            stage = "Choose a destination"
            mappings = self.profile.enabled_destinations()
        self.hud.set_state(
            stage=stage,
            progress=self._progress_text(),
            mappings=mappings,
            standard_keys=bool(
                self.profile.standard_key_destinations
                and (
                    qualifier is not None
                    or not self.profile.qualifier_enabled
                    or self.profile.missing_qualifier == "unclassified"
                )
            ),
        )
        self.progress_changed.emit(self._progress_text())

    def _show_current(self):
        if not self.active or self.queue is None:
            return
        total = len(self.queue)
        examined = 0
        while examined < total:
            if self.position >= total:
                self.position = 0
            if (
                self.position in self._missing_indices
                or self._decision_at(self.position) is not None
            ):
                self.position += 1
                examined += 1
                continue
            path = self.queue.path_at(self.position)
            if path is not None and path.exists():
                if self._select_media_by_path(path):
                    self._update_hud()
                    QTimer.singleShot(0, self.hud.raise_)
                    return
            self._missing_indices.add(self.position)
            self.position += 1
            examined += 1
        self._show_completion()

    def _select_media_by_path(self, media_path: Path) -> bool:
        context = self._browser_context or self.resolve_browser_context()
        model = context["model"]
        proxy = context["proxy"]
        image_list = context["image_list"]
        try:
            source_row = model.get_index_for_path(self._absolute_path(media_path))
        except Exception:
            source_row = -1
        if source_row < 0:
            return False
        source_index = model.index(source_row, 0)
        proxy_index = proxy.mapFromSource(source_index)
        if not proxy_index.isValid():
            return False
        view = image_list.list_view
        selection_model = view.selectionModel()
        if selection_model is not None:
            selection_model.setCurrentIndex(
                proxy_index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect,
            )
        else:
            view.setCurrentIndex(proxy_index)
        try:
            view.scrollTo(proxy_index, QAbstractItemView.ScrollHint.PositionAtCenter)
        except Exception:
            view.scrollTo(proxy_index)
        if context.get("name") == "secondary":
            manager = getattr(self.main_window, "_context_switch_manager", None)
            owner = context.get("owner")
            if manager is not None and owner is not None:
                manager.switch_to_context(
                    {
                        "name": "secondary",
                        "proxy_index": proxy_index,
                        "image_list_model": model,
                        "proxy_image_list_model": proxy,
                        "tag_counter_model": owner.tag_counter_model,
                        "image_list": image_list,
                    }
                )
        # currentChanged is synchronous. Usually it has already loaded the
        # main viewer, so loading again would clear/rebuild the scene twice and
        # produce a visible flash. Fall back only when that signal was
        # suppressed by masonry guards or routed to another viewer.
        viewer = self.main_window.image_viewer
        loaded_index = getattr(viewer, "proxy_image_index", None)
        viewer_has_target = False
        try:
            viewer_has_target = bool(
                loaded_index is not None
                and loaded_index.isValid()
                and loaded_index.model() == proxy_index.model()
                and loaded_index.row() == proxy_index.row()
                and loaded_index.column() == proxy_index.column()
            )
            if viewer_has_target:
                loaded_media = loaded_index.data(Qt.ItemDataRole.UserRole)
                requested_media = proxy_index.data(Qt.ItemDataRole.UserRole)
                loaded_path = getattr(loaded_media, "path", None)
                requested_path = getattr(requested_media, "path", None)
                if loaded_path is not None or requested_path is not None:
                    viewer_has_target = (
                        loaded_path is not None
                        and requested_path is not None
                        and self._absolute_path(loaded_path)
                        == self._absolute_path(requested_path)
                    )
        except (AttributeError, RuntimeError, TypeError):
            viewer_has_target = False
        if not viewer_has_target:
            viewer.load_image(proxy_index)
        return True

    def _show_completion(self):
        if self.queue is None:
            return
        moved = sum(
            1
            for record in self.history[: self.history_cursor]
            if record.operation is not None and record.operation.mode == "move"
        )
        copied = sum(
            1
            for record in self.history[: self.history_cursor]
            if record.operation is not None and record.operation.mode == "copy"
        )
        skipped = self._skip_count() + len(self._missing_indices)
        self.hud.set_state(
            stage="Quick Sort complete",
            progress=f"{len(self.queue):,} / {len(self.queue):,}",
            mappings=[],
        )
        detail_parts = []
        if moved:
            detail_parts.append(f"{moved:,} moved")
        if copied:
            detail_parts.append(f"{copied:,} copied")
        if skipped:
            detail_parts.append(f"{skipped:,} skipped")
        self.hud.show_feedback(
            "SORT COMPLETE",
            " · ".join(detail_parts) or "No files changed",
            "#62E7D8",
            action_text="Start fresh",
            persistent=True,
        )

    def _advance_after_record(self, record: QuickSortHistoryRecord):
        if self.history_cursor < len(self.history):
            self.history = self.history[: self.history_cursor]
        self.history.append(record)
        self.history_cursor = len(self.history)
        self._decisions[record.index] = record
        self._persist_session_state()
        self.pending_qualifier_id = None
        self.position = record.index + 1
        self._show_current()

    def _run_worker(
        self,
        callback: Callable[[], object],
        finished: Callable[[object, Exception | None], None],
    ):
        self.busy = True
        token = self._session_token
        worker = _QuickSortWorker(callback)
        self._workers.add(worker)

        def _finished(result, error):
            self._workers.discard(worker)
            if token != self._session_token:
                return
            self.busy = False
            finished(result, error)
            if self._finish_when_idle and self.active and not self.busy:
                self._finish_when_idle = False
                self.finish_session()

        worker.signals.finished.connect(_finished)
        self.thread_pool.start(worker)

    def _collision_policy_for_operation(
        self,
        source: Path,
        destination_directory: Path,
    ) -> str | None:
        if self.profile is None or self.profile.collision_policy != "ask":
            return self.profile.collision_policy if self.profile is not None else None
        requested = destination_directory / source.name
        try:
            has_collision = self.file_service.has_requested_collision(
                source=source,
                destination_directory=destination_directory,
                include_sidecars=self.profile.include_sidecars,
            )
        except Exception as exc:  # bundle validation belongs in the UI thread
            self.hud.show_feedback("INVALID FILE BUNDLE", str(exc), "#E87979")
            return None
        if not has_collision:
            return "ask"
        box = QMessageBox(self.main_window)
        box.setWindowTitle("Quick Sort collision")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"{requested.name} already exists.")
        box.setInformativeText("Create a numbered filename or skip this image?")
        append_button = box.addButton("Append number", QMessageBox.ButtonRole.AcceptRole)
        skip_button = box.addButton("Skip", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is append_button:
            return "append"
        if clicked is skip_button:
            return "skip"
        return None

    def _prepare_current_video_for_move(self, source: Path, callback: Callable[[], None]):
        viewer = self.main_window.image_viewer
        player = getattr(viewer, "video_player", None)
        video_path = getattr(player, "video_path", None)
        if player is None or not video_path:
            callback()
            return
        try:
            matches = self._absolute_path(video_path) == self._absolute_path(source)
        except Exception:
            matches = False
        if not matches:
            callback()
            return
        try:
            player.cleanup()
            QApplication.processEvents()
        except Exception:
            pass
        QTimer.singleShot(120, callback)

    def classify_current(self, destination: QuickSortMapping):
        if (
            not self.active
            or self.busy
            or self.profile is None
            or self.queue is None
            or self.position >= len(self.queue)
        ):
            return
        if self._decision_at(self.position) is not None:
            self.hud.show_feedback(
                "ALREADY SORTED",
                "Use Ctrl+Z to change this decision",
                "#F2C96D",
            )
            return
        qualifier = self._qualifier_by_id(self.pending_qualifier_id)
        if (
            self.profile.qualifier_enabled
            and qualifier is None
            and self.profile.missing_qualifier == "require"
        ):
            self.hud.show_feedback(
                f"CHOOSE {self.profile.qualifier_name.upper()}",
                "Then choose a destination",
                "#F2C96D",
            )
            return
        source = self.queue.path_at(self.position)
        if source is None or not source.exists():
            self.hud.show_feedback("MISSING FILE", "Skipping unavailable media", "#E87979")
            self._missing_indices.add(self.position)
            self.position += 1
            self._show_current()
            return
        try:
            destination_directory = self.profile.route_directory(
                destination,
                qualifier,
                fallback_base=Path(self.queue.directory_path or source.parent),
            )
        except QuickSortValidationError as exc:
            self.hud.show_feedback("INVALID ROUTE", str(exc), "#E87979")
            return
        collision_policy = self._collision_policy_for_operation(
            source,
            destination_directory,
        )
        if collision_policy is None:
            return
        record_index = self.position
        source_identity = self._record_source_identity(record_index)
        profile = self.profile
        self.hud.show_feedback(
            destination.name.upper(),
            "Moving…" if profile.operation_mode == "move" else "Copying…",
            destination.color,
        )

        def _launch():
            self._run_worker(
                lambda: self.file_service.execute(
                    source=source,
                    destination_directory=destination_directory,
                    mode=profile.operation_mode,
                    include_sidecars=profile.include_sidecars,
                    collision_policy=collision_policy,
                ),
                lambda result, error: self._classification_finished(
                    result,
                    error,
                    index=record_index,
                    destination=destination,
                    qualifier=qualifier,
                    source_identity=source_identity,
                ),
            )

        if profile.operation_mode == "move":
            # Video backends may need a short handle-release delay.  Claim the
            # controller immediately so a second classification cannot be
            # queued during that window.
            self.busy = True
            self._prepare_current_video_for_move(source, _launch)
        else:
            _launch()

    def _classification_finished(
        self,
        result: QuickSortFileResult | None,
        error: Exception | None,
        *,
        index: int,
        destination: QuickSortMapping,
        qualifier: QuickSortMapping | None,
        source_identity: dict,
    ):
        if error is not None:
            title = "DESTINATION EXISTS" if isinstance(error, QuickSortCollisionError) else "SORT FAILED"
            self.hud.show_feedback(title, str(error), "#E87979")
            self._show_current()
            return
        if result is None:
            return
        qualifier_detail = f" · {qualifier.name}" if qualifier is not None else ""
        if result.skipped:
            record = QuickSortHistoryRecord(
                index=index,
                label="Skip collision",
                color="#F2C96D",
                destination_id=destination.id,
                qualifier_id=qualifier.id if qualifier is not None else None,
                skipped=True,
                **source_identity,
            )
            self.hud.show_feedback(
                "SKIPPED",
                f"{result.message} · {self._skip_count() + 1:,} skipped",
                "#F2C96D",
            )
        else:
            verb = "Moved" if result.operation and result.operation.mode == "move" else "Copied"
            record = QuickSortHistoryRecord(
                index=index,
                label=f"{destination.name}{qualifier_detail}",
                color=destination.color,
                destination_id=destination.id,
                qualifier_id=qualifier.id if qualifier is not None else None,
                operation=result.operation,
                **source_identity,
            )
            route_count = self._route_count(
                destination.id,
                qualifier.id if qualifier is not None else None,
            ) + 1
            self.hud.show_feedback(
                f"[{destination.key}]  {destination.name.upper()}",
                f"{verb}{qualifier_detail} · {route_count:,} sorted here",
                destination.color,
            )
        self._advance_after_record(record)

    def skip_current(self):
        if (
            not self.active
            or self.busy
            or self.queue is None
            or self.position >= len(self.queue)
        ):
            return
        existing = self._decision_at(self.position)
        if existing is not None:
            self.position += 1
            self._show_current()
            return
        record = QuickSortHistoryRecord(
            index=self.position,
            label="Skip",
            color="#93A5B4",
            skipped=True,
            **self._record_source_identity(self.position),
        )
        skipped_count = self._skip_count() + 1
        self.hud.show_feedback(
            "SKIPPED",
            f"File left in place · {skipped_count:,} skipped",
            "#93A5B4",
        )
        self._advance_after_record(record)

    def browse(self, offset: int):
        if not self.active or self.busy or self.queue is None:
            return
        if len(self.queue) == 0:
            return
        target = max(0, min(len(self.queue) - 1, self.position + int(offset)))
        if target == self.position:
            return
        if target < len(self.queue):
            decision = self._decision_at(target)
            if decision is not None and decision.operation is not None:
                self.hud.show_feedback(
                    "ITEM ALREADY MOVED",
                    "Use Ctrl+Z to restore the latest decision",
                    "#F2C96D",
                )
                return
        self.pending_qualifier_id = None
        self.position = target
        self._show_current()

    def undo(self):
        if not self.active or self.busy or self.history_cursor <= 0:
            return
        record = self.history[self.history_cursor - 1]
        if record.operation is None:
            self.history_cursor -= 1
            self._decisions.pop(record.index, None)
            self._persist_session_state()
            self.position = record.index
            self.pending_qualifier_id = record.qualifier_id
            self.hud.show_feedback("UNDID SKIP", "Decision restored", "#93A5B4")
            self._show_current()
            return

        def _finished(_result, error):
            if error is not None:
                self.hud.show_feedback("UNDO FAILED", str(error), "#E87979")
                return
            self.history_cursor -= 1
            self._decisions.pop(record.index, None)
            self._persist_session_state()
            self.position = record.index
            self.pending_qualifier_id = record.qualifier_id
            self.hud.show_feedback("UNDONE", record.label, record.color)
            self._show_current()

        self._run_worker(lambda: self.file_service.undo(record.operation), _finished)

    def redo(self):
        if (
            not self.active
            or self.busy
            or self.history_cursor >= len(self.history)
        ):
            return
        record = self.history[self.history_cursor]
        if record.operation is None:
            self.history_cursor += 1
            self._decisions[record.index] = record
            self._persist_session_state()
            self.position = record.index + 1
            self.pending_qualifier_id = None
            self.hud.show_feedback("REDID SKIP", "Advanced", "#93A5B4")
            self._show_current()
            return

        def _finished(_result, error):
            if error is not None:
                self.hud.show_feedback("REDO FAILED", str(error), "#E87979")
                return
            self.history_cursor += 1
            self._decisions[record.index] = record
            self._persist_session_state()
            self.position = record.index + 1
            self.pending_qualifier_id = None
            self.hud.show_feedback("REDONE", record.label, record.color)
            self._show_current()

        self._run_worker(lambda: self.file_service.redo(record.operation), _finished)

    def toggle_fullscreen(self):
        main = self.main_window
        if main._viewer_is_fullscreen(main.image_viewer):
            main._restore_fullscreen_viewer(main.image_viewer, close_window=True)
        else:
            main._enter_viewer_fullscreen(main.image_viewer)
        QTimer.singleShot(0, self.hud.reposition)

    def handle_key_event(self, event, event_type) -> bool:
        if not self.active:
            return False
        if event_type == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        if event_type != QEvent.Type.KeyPress:
            return False
        event.accept()
        if event.isAutoRepeat():
            return True
        key = event.key()
        modifiers = event.modifiers()
        if self.busy:
            if (
                key == Qt.Key.Key_Escape
                and modifiers == Qt.KeyboardModifier.NoModifier
            ):
                self.finish_session()
            return True
        if key == Qt.Key.Key_Escape and modifiers == Qt.KeyboardModifier.NoModifier:
            if self.pending_qualifier_id is not None:
                self.pending_qualifier_id = None
                detail = "Choose a qualifier"
                if (
                    self.profile is not None
                    and self.profile.missing_qualifier == "unclassified"
                ):
                    detail = "Choose a qualifier or destination"
                self.hud.show_feedback(
                    "STAGE CLEARED",
                    detail,
                    "#93A5B4",
                )
                self._update_hud()
                return True
            self.finish_session()
            return True
        if (
            key == Qt.Key.Key_Backspace
            and modifiers == Qt.KeyboardModifier.NoModifier
            and self.pending_qualifier_id is not None
        ):
            self.pending_qualifier_id = None
            self._update_hud()
            return True
        if key == Qt.Key.Key_F11 and modifiers == Qt.KeyboardModifier.NoModifier:
            self.toggle_fullscreen()
            return True
        if (
            key == Qt.Key.Key_Z
            and modifiers == Qt.KeyboardModifier.ControlModifier
        ):
            self.undo()
            return True
        if (
            key == Qt.Key.Key_Y
            and modifiers == Qt.KeyboardModifier.ControlModifier
        ) or (
            key == Qt.Key.Key_Z
            and modifiers
            == (
                Qt.KeyboardModifier.ControlModifier
                | Qt.KeyboardModifier.ShiftModifier
            )
        ):
            self.redo()
            return True
        if key == Qt.Key.Key_Space and modifiers == Qt.KeyboardModifier.NoModifier:
            self.skip_current()
            return True
        if (
            modifiers == Qt.KeyboardModifier.NoModifier
            and key in {Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_PageDown}
        ):
            self.browse(1)
            return True
        if (
            modifiers == Qt.KeyboardModifier.NoModifier
            and key in {Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_PageUp}
        ):
            self.browse(-1)
            return True
        if key == Qt.Key.Key_Home and modifiers == Qt.KeyboardModifier.NoModifier:
            self.browse(-10**12)
            return True
        if key == Qt.Key.Key_End and modifiers == Qt.KeyboardModifier.NoModifier:
            self.browse(10**12)
            return True
        if self.profile is None:
            return True
        sequence = self.key_sequence_from_event(event)
        if not sequence:
            return True
        if self.profile.qualifier_enabled:
            if self.pending_qualifier_id is None:
                qualifier = self.profile.mapping_for_key(sequence, qualifier=True)
                if qualifier is not None:
                    self.pending_qualifier_id = qualifier.id
                    self.hud.show_feedback(
                        qualifier.name.upper(),
                        "Now choose a destination",
                        qualifier.color,
                    )
                    self._update_hud()
                    return True
                if self.profile.missing_qualifier == "require":
                    self.hud.show_feedback(
                        f"CHOOSE {self.profile.qualifier_name.upper()}",
                        "No qualifier is assigned to that key",
                        "#F2C96D",
                    )
                    return True
            else:
                normalized_sequence = normalize_key_sequence(sequence).casefold()
                destination = next(
                    (
                        mapping
                        for mapping in self.profile.enabled_destinations()
                        if normalize_key_sequence(mapping.key).casefold()
                        == normalized_sequence
                    ),
                    None,
                )
                if destination is not None:
                    self.classify_current(destination)
                    return True
                replacement = self.profile.mapping_for_key(
                    sequence,
                    qualifier=True,
                )
                if replacement is not None:
                    self.pending_qualifier_id = replacement.id
                    self.hud.show_feedback(
                        replacement.name.upper(),
                        "Qualifier changed · now choose a destination",
                        replacement.color,
                    )
                    self._update_hud()
                    return True
                destination = self.profile.mapping_for_key(
                    sequence,
                    qualifier=False,
                )
                if destination is not None:
                    self.classify_current(destination)
                    return True
        destination = self.profile.mapping_for_key(sequence, qualifier=False)
        if destination is not None:
            self.classify_current(destination)
        else:
            self.hud.show_feedback(
                "UNASSIGNED KEY",
                sequence,
                "#93A5B4",
            )
        return True

    @classmethod
    def _path_within(cls, path: Path, root: Path) -> bool:
        return cls._relative_to_root(path, root) is not None

    def _reconcile_browser_model(
        self,
        operations: list[QuickSortFileOperation],
        context: dict | None = None,
    ):
        if not operations:
            return
        context = context or self._browser_context or self.resolve_browser_context()
        model = context["model"]
        root_value = getattr(model, "_directory_path", None)
        database = getattr(model, "_db", None)
        if root_value is None or database is None:
            raise RuntimeError(
                f"{context.get('name', 'browser')} has no writable folder index."
            )
        root = self._absolute_path(root_value)
        remove_rel_paths: list[str] = []
        added_destinations: list[Path] = []
        for operation in operations:
            source = self._absolute_path(operation.source)
            destination = self._absolute_path(operation.destination)
            source_rel = self._relative_to_root(source, root)
            destination_rel = self._relative_to_root(destination, root)
            if operation.mode == "move" and source_rel is not None:
                if destination_rel is not None:
                    old_rel = str(source_rel)
                    new_rel = str(destination_rel)
                    source_id = database.get_image_id(old_rel)
                    if source_id is None:
                        raise RuntimeError(
                            f"Folder index did not contain moved source {old_rel!r}."
                        )
                    renamed = database.rename_image_path(
                        old_rel,
                        new_rel,
                        directory_path=root,
                        replace_stale_destination=True,
                    )
                    if renamed is not True:
                        raise RuntimeError(
                            f"Folder index failed to rename {old_rel!r} to {new_rel!r}."
                        )
                else:
                    remove_rel_paths.append(str(source_rel))
            elif operation.mode == "move" and destination_rel is not None:
                # This model owns the destination but not the source (for
                # example Browser 1 -> Browser 2), so register it as a new row.
                added_destinations.append(destination)
            elif operation.mode == "copy" and destination_rel is not None:
                added_destinations.append(destination)
        if remove_rel_paths:
            unique_removals = sorted(set(remove_rel_paths))
            removed = database.remove_images_by_paths(unique_removals)
            if removed != len(unique_removals):
                raise RuntimeError(
                    "Folder index removed "
                    f"{removed!r} of {len(unique_removals)} moved paths."
                )
        if added_destinations:
            unique_destinations = list(dict.fromkeys(added_destinations))
            missing_before = [
                destination
                for destination in unique_destinations
                if database.get_image_id(
                    str(self._relative_to_root(destination, root))
                )
                is None
            ]
            inserted = model.add_generated_media_batch(unique_destinations)
            missing_after = [
                destination
                for destination in unique_destinations
                if database.get_image_id(
                    str(self._relative_to_root(destination, root))
                )
                is None
            ]
            if missing_after or inserted < len(missing_before):
                missing_names = ", ".join(path.name for path in missing_after)
                raise RuntimeError(
                    "Folder index registered "
                    f"{inserted!r} of {len(missing_before)} new destination paths"
                    + (f"; still missing: {missing_names}" if missing_names else "")
                    + "."
                )
            for operation in operations:
                if operation.mode != "copy":
                    continue
                source = self._absolute_path(operation.source)
                destination = self._absolute_path(operation.destination)
                source_rel = self._relative_to_root(source, root)
                destination_rel = self._relative_to_root(destination, root)
                if source_rel is None or destination_rel is None:
                    continue
                cloned = database.clone_curator_metadata(
                    str(source_rel),
                    str(destination_rel),
                )
                if cloned is not True:
                    raise RuntimeError(
                        "Folder index failed to copy curator metadata from "
                        f"{str(source_rel)!r} to {str(destination_rel)!r}."
                    )
        database.invalidate_order_cache()

    def _reconcile_browser_models(
        self,
        operations: list[QuickSortFileOperation],
        contexts: list[dict],
    ):
        errors: list[str] = []
        reconciled_roots: set[str] = set()
        for context in contexts:
            root = self._context_root(context)
            if root is None:
                continue
            root_key = os.path.normcase(str(root))
            if root_key in reconciled_roots:
                continue
            reconciled_roots.add(root_key)
            try:
                self._reconcile_browser_model(operations, context)
            except Exception as exc:  # noqa: BLE001 - combine all affected roots
                errors.append(f"{root}: {exc}")
        if errors:
            raise RuntimeError("\n".join(errors))

    def _reload_browser(self, context: dict):
        model = context.get("model")
        image_list = context.get("image_list")
        directory = getattr(model, "_directory_path", None)
        if model is None or image_list is None or directory is None:
            return
        if context.get("name") != "secondary":
            # A move makes the pre-sort selection path invalid. Asking the
            # paginated masonry view to asynchronously recenter onto that
            # stale path can overlap its model reset and native paint pass.
            # Reload the same filter at a stable row instead.
            filter_text = str(image_list.filter_line_edit.text() or "")
            self.main_window._reload_directory_from_state(
                filter_text=filter_text,
                select_index=0,
                select_path=None,
            )
            return
        owner = context.get("owner")
        if owner is None:
            return
        filter_text = str(image_list.filter_line_edit.text() or "")
        media_type = str(image_list.media_type_combo_box.currentText() or "All")
        list_view = image_list.list_view
        current_index = list_view.currentIndex()
        select_index = int(current_index.row()) if current_index.isValid() else 0
        select_path = None
        if current_index.isValid():
            image = current_index.data(Qt.ItemDataRole.UserRole)
            if image is not None and getattr(image, "path", None) is not None:
                select_path = str(self._absolute_path(image.path))
        owner.load_directory(self._absolute_path(directory))
        image_list.media_type_combo_box.setCurrentText(media_type)
        image_list.filter_line_edit.setText(filter_text)
        apply_now = getattr(owner, "_apply_filter_now", None)
        if callable(apply_now):
            apply_now()
        restore_selection = getattr(
            self.main_window,
            "_restore_refresh_selection",
            None,
        )
        if callable(restore_selection):
            restore_selection(
                {
                    "dock": image_list,
                    "proxy_model": context.get("proxy"),
                },
                select_index=select_index,
                select_path=select_path,
            )

    def _reload_browsers(self, contexts: list[dict], active_context: dict):
        active_model = active_context.get("model")
        ordered = sorted(
            self._dedupe_contexts(contexts),
            key=lambda context: context.get("model") is active_model,
        )
        errors: list[str] = []
        for context in ordered:
            try:
                self._reload_browser(context)
            except Exception as exc:  # noqa: BLE001 - continue other browser reloads
                errors.append(f"{context.get('name', 'browser')}: {exc}")
        if errors:
            QMessageBox.warning(
                self.main_window,
                "Quick Sort refresh",
                "Some browser folders could not be reloaded:\n\n"
                + "\n".join(errors),
            )

    def finish_session(self, *, reload_browser: bool = True):
        if not self.active:
            return
        if self.busy:
            self._finish_when_idle = True
            self.hud.show_feedback(
                "PLEASE WAIT",
                "The current file operation is still finishing",
                "#F2C96D",
            )
            return
        applied_records = self.history[: self.history_cursor]
        operations = [
            record.operation
            for record in applied_records
            if record.operation is not None
        ]
        summary = {
            "total": len(self.queue) if self.queue is not None else 0,
            "changed": len(operations),
            "skipped": self._skip_count() + len(self._missing_indices),
            "remaining": max(
                0,
                (len(self.queue) if self.queue is not None else 0)
                - len(self._decisions)
                - len(self._missing_indices),
            ),
        }
        browser_context = self._browser_context or self.resolve_browser_context()
        operation_paths = [
            self._absolute_path(path)
            for operation in operations
            for path in (operation.source, operation.destination)
        ]
        affected_contexts = self._contexts_overlapping_paths(operation_paths)
        reconcile_contexts = self._dedupe_contexts(
            [browser_context, *affected_contexts]
        )
        reload_contexts = self._dedupe_contexts(
            [
                *self._coordinated_browser_contexts,
                *reconcile_contexts,
            ]
        )
        self._cancel_context_validation(reload_contexts)
        close_pending = bool(
            getattr(self.main_window, "_quick_sort_close_pending", False)
        )
        self.hud.hide()
        refresh_error: Exception | None = None
        try:
            self._reconcile_browser_models(operations, reconcile_contexts)
            if reload_browser and not close_pending:
                # Keep browser docks hidden while their models reset. Restoring
                # the dock layout first can make QListView paint against a
                # half-reset paginated model, which is unsafe in native Qt.
                self._reload_browsers(reload_contexts, browser_context)
        except Exception as exc:  # noqa: BLE001 - restore UI before reporting
            refresh_error = exc
        finally:
            self._restore_layout()
        if refresh_error is not None:
            QMessageBox.warning(
                self.main_window,
                "Quick Sort refresh",
                "The files were sorted, but TagGUI could not fully refresh its "
                f"folder index yet:\n\n{refresh_error}\n\n"
                "Reload the folder to reconcile it.",
            )
        self.active = False
        self.busy = False
        self._session_token += 1
        self.profile = None
        self.queue = None
        self._resume_session_key = None
        self._browser_context = None
        self._coordinated_browser_contexts.clear()
        self.pending_qualifier_id = None
        self.history.clear()
        self.history_cursor = 0
        self._decisions.clear()
        self._missing_indices.clear()
        self._finish_when_idle = False
        self.active_changed.emit(False)
        self.session_finished.emit(summary)
        if close_pending:
            self.main_window._quick_sort_close_pending = False
            QTimer.singleShot(0, self.main_window.close)

    def ensure_finished_before_close(self):
        """Restore the real layout before MainWindow persists its close state."""
        if not self.active:
            return
        if self.busy:
            return
        self.finish_session(reload_browser=False)
