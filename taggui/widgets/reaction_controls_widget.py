"""Reusable reaction controls cluster for toolbar and overlay hosting."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QToolButton, QWidget

from widgets.rating_controls import ReactionToggleButton, StarRatingWidget


class ReactionControlsWidget(QFrame):
    """Compact star/love/bomb cluster with attach/detach toggle."""

    hover_changed = Signal(bool)

    def __init__(self, toolbar_manager, *, overlay_mode: bool = False, parent=None):
        super().__init__(parent)
        self.toolbar_manager = toolbar_manager
        self._overlay_mode = bool(overlay_mode)
        self.setObjectName("reactionControlsWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        self._host_toggle_button = self._make_action_button(
            toolbar_manager.reaction_controls_host_toggle_action,
            role="host_toggle",
        )
        layout.addWidget(self._host_toggle_button)

        spacer = QWidget(self)
        spacer.setFixedWidth(4)
        spacer.setObjectName("reactionControlsSpacer")
        layout.addWidget(spacer)

        self.rating_widget = StarRatingWidget(self)
        layout.addWidget(self.rating_widget)

        self.love_button = ReactionToggleButton('love', self)
        layout.addWidget(self.love_button)

        self.bomb_button = ReactionToggleButton('bomb', self)
        layout.addWidget(self.bomb_button)

        self.set_overlay_mode(self._overlay_mode)

    def _make_action_button(self, action, *, role: str = "host_toggle"):
        button = QToolButton(self)
        button.setDefaultAction(action)
        button.setAutoRaise(False)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setProperty("controlRole", role)
        button.setFixedSize(14, 28)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        return button

    def sizeHint(self) -> QSize:
        return super().sizeHint().expandedTo(QSize(238, 42))

    def minimumSizeHint(self) -> QSize:
        return QSize(216, 40)

    def set_overlay_mode(self, overlay_mode: bool):
        self._overlay_mode = bool(overlay_mode)
        if self._overlay_mode:
            self.setStyleSheet(
                """
                #reactionControlsWidget {
                    background: rgba(18, 22, 28, 150);
                    border: 1px solid rgba(210, 220, 235, 80);
                    border-radius: 8px;
                }
                #reactionControlsWidget QToolButton[controlRole="host_toggle"] {
                    background: transparent;
                    color: rgba(226, 232, 240, 180);
                    border: none;
                    border-radius: 7px;
                    font-size: 12px;
                    font-weight: 700;
                    padding: 0px;
                }
                #reactionControlsWidget QToolButton[controlRole="host_toggle"]:hover {
                    background: rgba(255, 255, 255, 26);
                    color: rgba(248, 250, 252, 230);
                }
                #reactionControlsWidget QToolButton[controlRole="host_toggle"]:pressed {
                    background: rgba(255, 255, 255, 42);
                }
                #reactionControlsWidget QToolButton[controlRole="host_toggle"]:checked {
                    color: rgba(164, 243, 197, 220);
                }
                """
            )
        else:
            self.setStyleSheet(
                """
                #reactionControlsWidget {
                    background: transparent;
                    border: none;
                }
                #reactionControlsWidget QToolButton[controlRole="host_toggle"] {
                    background: transparent;
                    color: #d7dee8;
                    border: none;
                    border-radius: 7px;
                    font-size: 12px;
                    font-weight: 700;
                    padding: 0px;
                }
                #reactionControlsWidget QToolButton[controlRole="host_toggle"]:hover {
                    background: rgba(255, 255, 255, 0.08);
                    color: #f8fafc;
                }
                #reactionControlsWidget QToolButton[controlRole="host_toggle"]:pressed {
                    background: rgba(255, 255, 255, 0.14);
                }
                #reactionControlsWidget QToolButton[controlRole="host_toggle"]:checked {
                    color: #9ae6b4;
                }
                """
            )

    def enterEvent(self, event):
        self.hover_changed.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover_changed.emit(False)
        super().leaveEvent(event)
