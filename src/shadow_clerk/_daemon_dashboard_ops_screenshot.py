"""Shadow-clerk daemon: ダッシュボード 画面キャプチャ受け取りエンドポイント"""
# pylint: disable=duplicate-code  # POST ボディ解析・セッション解決の定型は各ハンドラで共通形
from __future__ import annotations
import base64
import datetime
import json
import logging
import os
from shadow_clerk import DATA_DIR
from shadow_clerk._daemon_constants import SESSION_FILE

logger = logging.getLogger("shadow-clerk")

# 拡張が送るのは png のみ。他の形式は受けない
_DATA_URL_PREFIX = "data:image/png;base64,"
# 4K のフルスクリーン png でも 12MB は超えないため、それ以上は不正とみなす
_MAX_IMAGE_BYTES = 12 * 1024 * 1024
# 書き込みを伴うので、ダッシュボードの bind とは別に、このエンドポイントだけ localhost に限る
_ALLOWED_CLIENTS = ("127.0.0.1", "::1", "::ffff:127.0.0.1")


class _DashboardHandlerScreenshotOps:
    """画面キャプチャの受け取り（ミックスイン）"""

    def _save_screenshot(self) -> None:
        """POST /api/screenshot — 拡張が撮ったタブのキャプチャを保存し、transcript に1行残す"""
        client = self.client_address[0] if self.client_address else ""
        if client not in _ALLOWED_CLIENTS:
            # ダッシュボード自体は外部からも見られる設定でありうるが、書き込みは通さない
            logger.warning("screenshot: 拒否 (client=%s)", client)
            self._send_json({"status": "error", "message": "screenshot API is localhost only"})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)
            image = data.get("image") or ""
            title = (data.get("title") or "").strip()
            url = (data.get("url") or "").strip()
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            self._send_json({"status": "error", "message": "invalid request body"})
            return

        if not isinstance(image, str) or not image.startswith(_DATA_URL_PREFIX):
            self._send_json({"status": "error", "message": "image must be a png data URL"})
            return
        try:
            raw = base64.b64decode(image[len(_DATA_URL_PREFIX):], validate=True)
        except (ValueError, TypeError):
            self._send_json({"status": "error", "message": "image is not valid base64"})
            return
        if not raw or len(raw) > _MAX_IMAGE_BYTES:
            self._send_json({"status": "error", "message": "image size out of range"})
            return

        now = datetime.datetime.now()
        transcript_path = self._screenshot_target_transcript()
        filename = self._screenshot_filename(transcript_path, now)
        path = os.path.join(DATA_DIR, filename)

        try:
            with open(path, "wb") as f:
                f.write(raw)
        except OSError as e:
            logger.error("screenshot: 保存失敗 %s: %s", path, e)
            self._send_json({"status": "error", "message": f"failed to save: {e}"})
            return

        appended = False
        if transcript_path:
            appended = self._screenshot_append_transcript(transcript_path, now, filename, title, url)

        logger.info("screenshot: %s (transcript=%s)", filename, "yes" if appended else "no")
        self._send_json({
            "status": "ok",
            "file": filename,
            "path": path,
            "transcript_appended": appended,
        })

    def _screenshot_target_transcript(self) -> str:
        """キャプチャを書き込む transcript のパス。書ける先が無ければ空文字列

        会議単位で記録している間は .clerk_session がその transcript を指す。
        会議モードでないときは日次の transcript(transcript-YYYYMMDD.txt)に
        記録が続いているので、recorder の出力先へ書く。
        """
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                p = f.read().strip()
            if p and os.path.exists(p):
                return p
        except OSError:
            pass
        p = getattr(getattr(self, "recorder", None), "output_path", "") or ""
        return p if os.path.exists(p) else ""

    @staticmethod
    def _screenshot_filename(transcript_path: str, now: datetime.datetime) -> str:
        """shot-<transcript の stem>-<HHMMSS>.png。会議外なら shot-<YYYYMMDD-HHMMSS>.png

        advice-<stem>.md / analysis-<stem>.md と同じ命名に揃えてあるので、
        transcript から対応するキャプチャを引ける。
        """
        hms = now.strftime("%H%M%S")
        stem = os.path.splitext(os.path.basename(transcript_path))[0] if transcript_path else ""
        if stem.startswith("transcript-"):
            return f"shot-{stem[len('transcript-'):]}-{hms}.png"
        return f"shot-{now.strftime('%Y%m%d')}-{hms}.png"

    @staticmethod
    def _screenshot_append_transcript(transcript_path: str, now: datetime.datetime,
                                      filename: str, title: str, url: str) -> bool:
        """transcript に [画面] 行を追記する

        話者は [自分]/[相手] の2値なので、キャプチャは [画面] という第3のラベルにして
        発言と区別できるようにしてある。要約・翻訳からは除外していないため、
        行頭に「画面キャプチャ:」を付けて LLM が意味を取れる形にしている。
        """
        parts = [f"画面キャプチャ: {filename}"]
        if title:
            parts.append(title.replace("|", "/"))
        if url:
            parts.append(url.replace("|", "/"))
        line = f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] [画面] {' | '.join(parts)}\n"
        try:
            with open(transcript_path, "a", encoding="utf-8") as f:
                f.write(line)
            return True
        except OSError as e:
            logger.error("screenshot: transcript 追記失敗 %s: %s", transcript_path, e)
            return False
