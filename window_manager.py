"""Window detection and focus management via win32 APIs."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
from typing import Final

import pygetwindow as gw

__all__ = ["get_foreground_window", "get_window_region", "is_window_focused"]

_user32 = ctypes.windll.user32

_MIN_WINDOW_DIM: Final[int] = 200


def _enable_dpi_awareness() -> None:
    """Set per-monitor DPI awareness so coordinates match mss's physical-pixel capture."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (OSError, AttributeError):
        _user32.SetProcessDPIAware()


_enable_dpi_awareness()


def _get_client_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Get the client area (content, no chrome) in screen coordinates.

    Returns:
        (x, y, width, height) of the client area.

    Raises:
        RuntimeError: If the win32 calls fail or return invalid values.
    """
    client_rect = ctypes.wintypes.RECT()
    if not _user32.GetClientRect(hwnd, ctypes.byref(client_rect)):
        raise RuntimeError(f"GetClientRect failed for HWND {hwnd}")

    point = ctypes.wintypes.POINT(0, 0)
    if not _user32.ClientToScreen(hwnd, ctypes.byref(point)):
        raise RuntimeError(f"ClientToScreen failed for HWND {hwnd}")

    w, h = client_rect.right, client_rect.bottom
    if w <= 0 or h <= 0:
        raise RuntimeError(f"Invalid client rect dimensions: {w}x{h}")

    return (point.x, point.y, w, h)


def get_window_region(window: gw.Win32Window) -> tuple[int, int, int, int]:
    """Return the client area (x, y, width, height) excluding browser chrome.

    Raises:
        RuntimeError: If the window geometry cannot be read or is invalid.
    """
    try:
        return _get_client_rect(window._hWnd)
    except (RuntimeError, AttributeError) as exc:
        raise RuntimeError(f"Failed to read window geometry: {exc}") from exc


def get_foreground_window() -> gw.Win32Window:
    """Return the current foreground window as a Win32Window.

    Raises:
        RuntimeError: If no foreground window or it's below the minimum size.
    """
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        raise RuntimeError("No foreground window detected.")

    try:
        window = gw.Win32Window(hwnd)
    except (ValueError, TypeError, OSError, AttributeError) as exc:
        raise RuntimeError(f"Cannot wrap foreground HWND: {exc}") from exc

    if window.width < _MIN_WINDOW_DIM or window.height < _MIN_WINDOW_DIM:
        raise RuntimeError(
            f"Foreground window too small ({window.width}x{window.height}), "
            f"minimum is {_MIN_WINDOW_DIM}x{_MIN_WINDOW_DIM}."
        )
    return window


def is_window_focused(window: gw.Win32Window) -> bool:
    """Check if the window is the current foreground window."""
    try:
        return bool(window.isActive)
    except (AttributeError, OSError):
        return False
