"""Compact toolbar widget for structured review marks."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QToolButton

from utils.review_marks import ReviewFlag


class ReviewControlsWidget(QFrame):
    """Clickable toolbar strip for review rank and flags."""

    rank_requested = Signal(int)
    flag_requested = Signal(str)

    _RANK_COLORS = {
        1: "#fbbf24",
        2: "#60a5fa",
        3: "#4ade80",
        4: "#c084fc",
        5: "#fb923c",
    }
    _FLAG_SPECS = (
        ("idea", "*", "#2dd4bf", ReviewFlag.IDEA),
        ("warning", "!", "#f59e0b", ReviewFlag.WARNING),
        ("question", "?", "#818cf8", ReviewFlag.QUESTION),
        ("reject", "X", "#f87171", ReviewFlag.REJECT),
    )
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("reviewControlsWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        self._rank_buttons = {}
        self._flag_buttons = {}

        for rank in range(1, 6):
            button = self._make_button(str(rank))
            button.setToolTip("Add badge to image")
            button.clicked.connect(
                lambda _checked=False, current_rank=rank: self.rank_requested.emit(int(current_rank))
            )
            layout.addWidget(button)
            self._rank_buttons[rank] = button

        for flag_name, label, _color, _flag in self._FLAG_SPECS:
            button = self._make_button(label)
            button.setToolTip("Add badge to image")
            button.clicked.connect(
                lambda _checked=False, current_flag=flag_name: self.flag_requested.emit(str(current_flag))
            )
            layout.addWidget(button)
            self._flag_buttons[flag_name] = button

        self.setStyleSheet(
            """
            #reviewControlsWidget {
                background: transparent;
                border: none;
            }
            """
        )
        self.set_state(0, 0, mixed=False)

    def _make_button(self, text: str) -> QToolButton:
        button = QToolButton(self)
        button.setText(text)
        button.setCheckable(True)
        button.setAutoRaise(False)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedSize(26, 26)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        return button

    def sizeHint(self) -> QSize:
        return super().sizeHint().expandedTo(QSize(264, 36))

    def minimumSizeHint(self) -> QSize:
        return QSize(248, 34)

    def set_state(self, review_rank: int, review_flags: int, *, mixed: bool = False):
        mixed = bool(mixed)
        for rank, button in self._rank_buttons.items():
            blocker = button.blockSignals(True)
            checked = (not mixed) and int(review_rank or 0) == int(rank)
            button.setChecked(checked)
            button.blockSignals(blocker)
            self._apply_button_style(button, self._RANK_COLORS[rank], checked, mixed)

        for flag_name, _label, color, flag in self._FLAG_SPECS:
            button = self._flag_buttons[flag_name]
            blocker = button.blockSignals(True)
            checked = (not mixed) and bool(int(review_flags or 0) & int(flag))
            button.setChecked(checked)
            button.blockSignals(blocker)
            self._apply_button_style(button, color, checked, mixed)

    def _apply_button_style(self, button: QToolButton, accent_color: str, checked: bool, mixed: bool):
        if mixed:
            button.setStyleSheet(
                """
                QToolButton {
                    border: 1px solid rgba(148, 163, 184, 140);
                    border-radius: 7px;
                    background: rgba(30, 41, 59, 0.24);
                    color: rgba(248, 250, 252, 170);
                    font-weight: 700;
                    font-size: 13px;
                    padding: 0px;
                }
                """
            )
            return
        if checked:
            button.setStyleSheet(
                f"""
                QToolButton {{
                    border: 1px solid {accent_color};
                    border-radius: 7px;
                    background: {accent_color};
                    color: #111827;
                    font-weight: 700;
                    font-size: 13px;
                    padding: 0px;
                }}
                """
            )
            return
        button.setStyleSheet(
            f"""
            QToolButton {{
                border: 1px solid rgba(148, 163, 184, 140);
                border-radius: 7px;
                background: rgba(30, 41, 59, 0.18);
                color: #f8fafc;
                font-weight: 700;
                font-size: 13px;
                padding: 0px;
            }}
            QToolButton:hover {{
                border-color: {accent_color};
                color: {accent_color};
                background: rgba(255, 255, 255, 0.06);
            }}
            """
        )
