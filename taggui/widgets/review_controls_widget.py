"""Compact toolbar widget for structured review marks."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QMenu, QToolButton

from utils.review_marks import (
    get_review_badge_corner_radius,
    get_review_badge_font_size,
    get_review_badge_spec_for_id,
    get_review_badge_specs,
    get_review_badge_text_color,
)


class ReviewControlsWidget(QFrame):
    """Clickable toolbar strip for structured review marks."""

    rank_requested = Signal(int)
    flag_requested = Signal(str)
    clear_requested = Signal(str)
    filter_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("reviewControlsWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(6, 4, 6, 4)
        self._layout.setSpacing(4)
        self._buttons_by_id = {}
        self._clear_button = None

        self.setStyleSheet(
            """
            #reviewControlsWidget {
                background: transparent;
                border: none;
            }
            """
        )
        self.refresh_badge_specs()

    def sizeHint(self) -> QSize:
        return super().sizeHint().expandedTo(QSize(264, 36))

    def minimumSizeHint(self) -> QSize:
        return QSize(248, 34)

    def refresh_badge_specs(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._buttons_by_id.clear()
        self._clear_button = None

        for spec in get_review_badge_specs():
            button = self._make_button(spec.badge_id, spec.label, spec.title)
            self._layout.addWidget(button)
            self._buttons_by_id[spec.badge_id] = button

        self._layout.addSpacing(6)
        self._clear_button = self._make_clear_button()
        self._layout.addWidget(self._clear_button)

    def _make_button(self, badge_id: str, text: str, title: str) -> QToolButton:
        button = QToolButton(self)
        button.setText(str(text or ''))
        button.setToolTip(str(title or 'Add badge to image'))
        button.setCheckable(True)
        button.setAutoRaise(False)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedSize(26, 26)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.clicked.connect(
            lambda _checked=False, current_badge_id=badge_id: self._emit_badge_requested(current_badge_id)
        )
        return button

    def _emit_badge_requested(self, badge_id: str):
        spec = get_review_badge_spec_for_id(badge_id)
        if spec is None:
            return
        modifiers = QApplication.keyboardModifiers()
        if (modifiers & Qt.KeyboardModifier.ControlModifier) == Qt.KeyboardModifier.ControlModifier:
            filter_text = ''
            if spec.kind == 'rank':
                filter_text = f'review:{int(spec.rank or 0)}'
            elif spec.kind == 'flag':
                filter_text = f'review:{str(spec.flag_name or "").strip()}'
            if filter_text:
                self.filter_requested.emit(filter_text)
            return
        if spec.kind == 'rank':
            self.rank_requested.emit(int(spec.rank or 0))
        elif spec.kind == 'flag':
            self.flag_requested.emit(str(spec.flag_name or ''))

    def set_state(self, review_rank: int, review_flags: int, *, mixed: bool = False):
        mixed = bool(mixed)
        active_ids = set()
        for spec in get_review_badge_specs():
            if spec.kind == 'rank' and int(review_rank or 0) == int(spec.rank or 0):
                active_ids.add(spec.badge_id)
            elif spec.kind == 'flag' and bool(int(review_flags or 0) & int(spec.flag)):
                active_ids.add(spec.badge_id)

        for spec in get_review_badge_specs():
            button = self._buttons_by_id.get(spec.badge_id)
            if button is None:
                continue
            blocker = button.blockSignals(True)
            checked = (not mixed) and (spec.badge_id in active_ids)
            button.setChecked(checked)
            button.setText(spec.label)
            button.setToolTip(str(spec.title or 'Add badge to image'))
            button.blockSignals(blocker)
            self._apply_button_style(button, spec.color, checked, mixed)
        self._apply_clear_button_style()

    def _make_clear_button(self) -> QToolButton:
        button = QToolButton(self)
        button.setText('Clear')
        button.setToolTip('Clear review badges')
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setAutoRaise(False)
        button.setFixedHeight(26)

        menu = QMenu(button)
        clear_target_action = menu.addAction('Clear Selected')
        clear_target_action.triggered.connect(
            lambda *_args: self.clear_requested.emit('target')
        )
        clear_folder_action = menu.addAction('Clear Current Folder')
        clear_folder_action.triggered.connect(
            lambda *_args: self.clear_requested.emit('folder')
        )
        button.setMenu(menu)
        self._apply_clear_button_style(button)
        return button

    def _apply_button_style(self, button: QToolButton, accent_color: str, checked: bool, mixed: bool):
        text_color = get_review_badge_text_color()
        font_size = get_review_badge_font_size()
        radius = get_review_badge_corner_radius()
        if mixed:
            button.setStyleSheet(
                f"""
                QToolButton {{
                    border: 1px solid rgba(148, 163, 184, 140);
                    border-radius: {radius}px;
                    background: rgba(30, 41, 59, 0.24);
                    color: {text_color};
                    font-weight: 700;
                    font-size: {font_size}px;
                    padding: 0px;
                }}
                """
            )
            return
        if checked:
            button.setStyleSheet(
                f"""
                QToolButton {{
                    border: 1px solid {accent_color};
                    border-radius: {radius}px;
                    background: {accent_color};
                    color: {text_color};
                    font-weight: 700;
                    font-size: {font_size}px;
                    padding: 0px;
                }}
                """
            )
            return
        button.setStyleSheet(
            f"""
            QToolButton {{
                border: 1px solid rgba(148, 163, 184, 140);
                border-radius: {radius}px;
                background: rgba(30, 41, 59, 0.18);
                color: {text_color};
                font-weight: 700;
                font-size: {font_size}px;
                padding: 0px;
            }}
            QToolButton:hover {{
                border-color: {accent_color};
                color: {accent_color};
                background: rgba(255, 255, 255, 0.06);
            }}
            """
        )

    def _apply_clear_button_style(self, button: QToolButton | None = None):
        target = button or self._clear_button
        if target is None:
            return
        text_color = get_review_badge_text_color()
        font_size = get_review_badge_font_size()
        radius = get_review_badge_corner_radius()
        target.setStyleSheet(
            f"""
            QToolButton {{
                border: 1px solid rgba(148, 163, 184, 140);
                border-radius: {radius}px;
                background: rgba(30, 41, 59, 0.18);
                color: {text_color};
                font-weight: 600;
                font-size: {font_size}px;
                padding: 0px 8px;
            }}
            QToolButton:hover {{
                border-color: rgba(248, 113, 113, 210);
                color: rgba(248, 113, 113, 230);
                background: rgba(255, 255, 255, 0.06);
            }}
            QToolButton::menu-indicator {{
                image: none;
                width: 0px;
            }}
            """
        )
