"""Reusable main-viewer controls cluster for toolbar and overlay hosting."""

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import QFrame, QHBoxLayout, QToolButton, QWidget


class MainViewerControlsWidget(QFrame):
    """Compact main-viewer controls cluster with attach/detach toggle."""

    hover_changed = Signal(bool)

    def __init__(self, toolbar_manager, *, overlay_mode: bool = False, parent=None):
        super().__init__(parent)
        self.toolbar_manager = toolbar_manager
        self._overlay_mode = bool(overlay_mode)
        self.setObjectName("mainViewerControlsWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        self._host_toggle_button = self._make_action_button(
            toolbar_manager.main_viewer_controls_host_toggle_action,
            role="host_toggle",
        )
        layout.addWidget(self._host_toggle_button)

        spacer = QWidget(self)
        spacer.setFixedWidth(8)
        spacer.setObjectName("mainViewerControlsSpacer")
        layout.addWidget(spacer)

        self._buttons = [self._host_toggle_button]
        for action in (
            toolbar_manager.zoom_fit_best_action,
            toolbar_manager.zoom_in_action,
            toolbar_manager.zoom_original_action,
            toolbar_manager.zoom_out_action,
            toolbar_manager.always_show_controls_action,
            toolbar_manager.zoom_follow_mode_action,
        ):
            button = self._make_action_button(action)
            layout.addWidget(button)
            self._buttons.append(button)

        self.set_overlay_mode(self._overlay_mode)

    def _make_action_button(self, action, *, role: str = "viewer_action"):
        button = QToolButton(self)
        button.setDefaultAction(action)
        button.setAutoRaise(False)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setProperty("controlRole", role)
        if role == "host_toggle":
            button.setFixedSize(14, 28)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        else:
            button.setFixedSize(32, 32)
            button.setIconSize(QSize(18, 18))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            if action.icon().isNull():
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        return button

    def set_overlay_mode(self, overlay_mode: bool):
        self._overlay_mode = bool(overlay_mode)
        if self._overlay_mode:
            self.setStyleSheet(
                """
                #mainViewerControlsWidget {
                    background: rgba(18, 22, 28, 150);
                    border: 1px solid rgba(210, 220, 235, 80);
                    border-radius: 12px;
                }
                #mainViewerControlsWidget QToolButton[controlRole="viewer_action"] {
                    background: rgba(34, 40, 50, 150);
                    color: rgba(248, 250, 252, 235);
                    border: 1px solid rgba(255, 255, 255, 54);
                    border-radius: 7px;
                    font-size: 16px;
                    font-weight: 700;
                    padding: 0px;
                }
                #mainViewerControlsWidget QToolButton[controlRole="viewer_action"]:hover {
                    background: rgba(55, 65, 80, 200);
                    border-color: rgba(255, 255, 255, 110);
                }
                #mainViewerControlsWidget QToolButton[controlRole="viewer_action"]:pressed {
                    background: rgba(16, 20, 26, 220);
                }
                #mainViewerControlsWidget QToolButton[controlRole="viewer_action"]:checked {
                    background: rgba(46, 118, 74, 215);
                    border-color: rgba(163, 230, 186, 200);
                }
                #mainViewerControlsWidget QToolButton[controlRole="host_toggle"] {
                    background: transparent;
                    color: rgba(226, 232, 240, 180);
                    border: none;
                    border-radius: 7px;
                    font-size: 12px;
                    font-weight: 700;
                    padding: 0px;
                }
                #mainViewerControlsWidget QToolButton[controlRole="host_toggle"]:hover {
                    background: rgba(255, 255, 255, 26);
                    color: rgba(248, 250, 252, 230);
                }
                #mainViewerControlsWidget QToolButton[controlRole="host_toggle"]:pressed {
                    background: rgba(255, 255, 255, 42);
                }
                #mainViewerControlsWidget QToolButton[controlRole="host_toggle"]:checked {
                    color: rgba(164, 243, 197, 220);
                }
                """
            )
        else:
            self.setStyleSheet(
                """
                #mainViewerControlsWidget {
                    background: transparent;
                    border: none;
                }
                #mainViewerControlsWidget QToolButton[controlRole="viewer_action"] {
                    background: #2b2b2b;
                    color: #f8fafc;
                    border: 2px solid #555;
                    border-radius: 4px;
                    font-size: 16px;
                    font-weight: 700;
                    padding: 0px;
                }
                #mainViewerControlsWidget QToolButton[controlRole="viewer_action"]:hover {
                    border-color: #777;
                    background: #353535;
                }
                #mainViewerControlsWidget QToolButton[controlRole="viewer_action"]:checked {
                    border-color: #4CAF50;
                    background: #2d5a2d;
                }
                #mainViewerControlsWidget QToolButton[controlRole="host_toggle"] {
                    background: transparent;
                    color: #d7dee8;
                    border: none;
                    border-radius: 7px;
                    font-size: 12px;
                    font-weight: 700;
                    padding: 0px;
                }
                #mainViewerControlsWidget QToolButton[controlRole="host_toggle"]:hover {
                    background: rgba(255, 255, 255, 0.08);
                    color: #f8fafc;
                }
                #mainViewerControlsWidget QToolButton[controlRole="host_toggle"]:pressed {
                    background: rgba(255, 255, 255, 0.14);
                }
                #mainViewerControlsWidget QToolButton[controlRole="host_toggle"]:checked {
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
