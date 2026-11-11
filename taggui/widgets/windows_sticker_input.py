"""Foreground raw mouse fallback for Alt-clicks intercepted before Qt on Windows."""

import ctypes
from ctypes import wintypes

from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication


class RawDevice(ctypes.Structure):
    _fields_ = [('page', wintypes.WORD), ('usage', wintypes.WORD),
                ('flags', wintypes.DWORD), ('window', wintypes.HWND)]


class RawHeader(ctypes.Structure):
    _fields_ = [('kind', wintypes.DWORD), ('size', wintypes.DWORD),
                ('device', wintypes.HANDLE), ('param', wintypes.WPARAM)]


class RawMouse(ctypes.Structure):
    _fields_ = [('flags', wintypes.WORD), ('buttons', wintypes.DWORD),
                ('raw_buttons', wintypes.DWORD), ('x', wintypes.LONG),
                ('y', wintypes.LONG), ('extra', wintypes.DWORD)]


class MousePacket(ctypes.Structure):
    _fields_ = [('header', RawHeader), ('mouse', RawMouse)]


def enable_foreground_mouse_input():
    # A process can have only one registration per device class. Preserve
    # any registration already installed by a video backend or Qt itself.
    user32 = ctypes.windll.user32
    count = wintypes.UINT()
    size = ctypes.sizeof(RawDevice)
    registered_count = user32.GetRegisteredRawInputDevices(
        None,
        ctypes.byref(count),
        size,
    )
    if registered_count == 0xFFFFFFFF:
        return False
    if count.value:
        devices = (RawDevice * count.value)()
        result = user32.GetRegisteredRawInputDevices(devices, ctypes.byref(count), size)
        if result in (-1, 0xFFFFFFFF):
            return False
        if any(device.page == 1 and device.usage == 2 for device in devices):
            return True
    mouse = RawDevice(1, 2, 0, None)
    return bool(user32.RegisterRawInputDevices(ctypes.byref(mouse), 1, size))


def handle_raw_mouse(message, controls):
    msg = wintypes.MSG.from_address(int(message))
    if msg.message != 0x00FF:  # WM_INPUT
        return
    user32 = ctypes.windll.user32
    if not controls.items and not controls.raw_press and not user32.GetKeyState(0xA4) & 0x8000:  # VK_LMENU
        return
    packet = MousePacket()
    size = wintypes.UINT(ctypes.sizeof(packet))
    if user32.GetRawInputData(wintypes.HANDLE(msg.lParam), 0x10000003,
                              ctypes.byref(packet), ctypes.byref(size),
                              ctypes.sizeof(RawHeader)) != ctypes.sizeof(packet):
        return
    if packet.header.kind != 0:
        return
    buttons = packet.mouse.buttons
    if buttons & 4:  # RI_MOUSE_RIGHT_BUTTON_DOWN
        viewport = controls.view.viewport()
        cursor = QCursor.pos()
        if (QApplication.activePopupWidget() is None
                and QApplication.widgetAt(cursor) is viewport and not controls.menu_press):
            pos = viewport.mapFromGlobal(cursor)
            target = controls.target(pos)
            if target and (user32.GetKeyState(0xA4) & 0x8000 or controls.item_at(pos)):
                controls.begin_right_press(pos, target[1])
                controls.raw_press = controls.menu_press
    if controls.raw_press and not controls.raw_menu_timer.isActive():
        controls.preview_right_drag(controls.view.viewport().mapFromGlobal(QCursor.pos()))
    if buttons & 8 and controls.raw_press:  # RI_MOUSE_RIGHT_BUTTON_UP
        controls.raw_menu_timer.start()
