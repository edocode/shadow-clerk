"""Shadow-clerk daemon: 画面全体のキャプチャ（ブラウザ拡張の「画面全体」ボタン）

ブラウザ拡張は表示中のタブしか撮れない（chrome.desktopCapture は毎回選択画面を出す）。
画面全体は daemon が OS の仕組みで撮る:

- Linux の Wayland: デスクトップポータル（org.freedesktop.portal.Screenshot）を
  interactive=false で呼ぶ。GNOME では確認画面なしで撮れた。X11 向けの道具
  （scrot など）は Xwayland の窓しか見えず真っ黒になり、grim は GNOME が対応しない
- それ以外（Windows・macOS・X11）: mss。Windows と X11 は確認画面なし、macOS は
  初回に「画面収録」の許可が要る。Windows と macOS は未検証
"""
from __future__ import annotations

import logging
import os
import sys
import uuid
from urllib.parse import unquote, urlparse

logger = logging.getLogger("shadow-clerk")

# ポータルの応答待ち。確認画面が出る環境でも、人が操作できる程度には待つ
_PORTAL_TIMEOUT_SEC = 30.0


class ScreenCaptureError(RuntimeError):
    """画面全体を撮れなかった。message はそのまま拡張に返す"""


def capture_screen() -> bytes:
    """画面全体（全モニター）を png で返す"""
    if sys.platform == "linux" and (os.environ.get("WAYLAND_DISPLAY")
                                    or os.environ.get("XDG_SESSION_TYPE") == "wayland"):
        return _capture_portal()
    return _capture_mss()


def _capture_mss() -> bytes:
    try:
        import mss
        import mss.tools
    except ImportError as e:
        raise ScreenCaptureError("mss is not installed") from e
    try:
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[0])     # monitors[0] は全モニターを合わせた範囲
            return mss.tools.to_png(shot.rgb, shot.size)
    except mss.exception.ScreenShotError as e:
        raise ScreenCaptureError(f"screen capture failed: {e}") from e


def _capture_portal() -> bytes:
    """ポータルに撮らせて、保存された画像を読んで消す（ポータルは ~/Pictures などに書く）"""
    try:
        from jeepney import DBusAddress, MatchRule, message_bus, new_method_call
        from jeepney.io.blocking import Proxy, open_dbus_connection
    except ImportError as e:
        raise ScreenCaptureError("jeepney is not installed") from e
    token = "shadowclerk" + uuid.uuid4().hex
    try:
        with open_dbus_connection(bus="SESSION") as conn:
            # 応答は Request オブジェクトの Response シグナルで届く。パスは送り手の名前と token で決まるので、
            # 呼ぶ前に購読しておけば取りこぼさない
            sender = conn.unique_name[1:].replace(".", "_")
            rule = MatchRule(type="signal", interface="org.freedesktop.portal.Request", member="Response",
                             path=f"/org/freedesktop/portal/desktop/request/{sender}/{token}")
            Proxy(message_bus, conn).AddMatch(rule)
            with conn.filter(rule) as queue:
                portal = DBusAddress("/org/freedesktop/portal/desktop", bus_name="org.freedesktop.portal.Desktop",
                                     interface="org.freedesktop.portal.Screenshot")
                conn.send_and_get_reply(new_method_call(
                    portal, "Screenshot", "sa{sv}",
                    ("", {"handle_token": ("s", token), "interactive": ("b", False)})))
                code, results = conn.recv_until_filtered(queue, timeout=_PORTAL_TIMEOUT_SEC).body
    except TimeoutError as e:
        raise ScreenCaptureError("the screenshot portal did not respond") from e
    except Exception as e:  # pylint: disable=broad-except  # D-Bus の失敗（ポータル無し・セッションバス無し）はまとめて返す
        raise ScreenCaptureError(f"screenshot portal failed: {e}") from e
    if code != 0:
        # 1 は利用者が取り消した、2 はそれ以外の理由で終わった
        raise ScreenCaptureError(f"screenshot portal declined (response {code})")
    path = unquote(urlparse(results.get("uri", ("s", ""))[1]).path)
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        raise ScreenCaptureError(f"cannot read the portal's screenshot: {e}") from e
    try:
        os.remove(path)
    except OSError as e:
        logger.warning("screenshot: ポータルが書いた画像を消せません %s: %s", path, e)
    return data
