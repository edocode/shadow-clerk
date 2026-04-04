"""Shadow-clerk: Google Calendar 連携モニター

設定が有効な場合、Google Calendar のイベントを定期ポーリングし、
開始・終了時刻に応じて start_meeting / end_meeting コマンドを自動送信する。

依存: google-auth-oauthlib, google-api-python-client
  uv sync --extra gcal
"""
import datetime
import logging
import os
import re
import threading
import time

from shadow_clerk import DATA_DIR
from shadow_clerk._daemon_constants import COMMAND_FILE

logger = logging.getLogger("shadow-clerk.gcal")

# Google Calendar API スコープ (読み取り専用)
_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# ポーリング間隔 (秒)
_POLL_INTERVAL = 60


def _sanitize_name(name: str) -> str:
    """イベント名をファイル名 suffix 用にエスケープする（_daemon_recorder_command と同ロジック）"""
    name = re.sub(r'[/\\:*?"<>|\x00-\x1f]', '', name)
    name = name.replace('@', '')
    name = re.sub(r'\s+', '_', name.strip())
    return name[:50].rstrip('_')


def _get_credentials(credentials_file: str, token_file: str):
    """OAuth2 認証情報を取得する。トークンがなければブラウザ認証フローを起動。"""
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
    except ImportError as e:
        raise ImportError(
            "Google Calendar 連携には google-auth-oauthlib と google-api-python-client が必要です。\n"
            "  uv sync --extra gcal"
        ) from e

    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, _SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as f:
            f.write(creds.to_json())

    return creds


def _build_service(creds):
    from googleapiclient.discovery import build
    return build("calendar", "v3", credentials=creds)


def _fetch_events(service, calendar_id: str, now: datetime.datetime, lookahead_minutes: int = 120):
    """進行中〜今後 lookahead_minutes 分以内のイベントを取得する。
    進行中イベントを確実に含めるため time_min を 24 時間前に設定する。"""
    time_min = (now - datetime.timedelta(hours=24)).isoformat() + "Z"
    time_max = (now + datetime.timedelta(minutes=lookahead_minutes)).isoformat() + "Z"
    result = service.events().list(
        calendarId=calendar_id,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    return result.get("items", [])


def _parse_event_time(event_time: dict) -> datetime.datetime | None:
    """イベントの start/end 時刻を UTC-naive datetime に変換する"""
    if "dateTime" in event_time:
        dt_str = event_time["dateTime"]
        # タイムゾーンオフセットを除去して UTC naive にする
        try:
            import email.utils
            dt = datetime.datetime.fromisoformat(dt_str)
            # offset-aware → UTC naive
            if dt.tzinfo is not None:
                dt = dt.utctimetuple()
                dt = datetime.datetime(*dt[:6])
            return dt
        except ValueError:
            return None
    return None  # 終日イベントはスキップ


class GCalMonitor:
    """Google Calendar を定期ポーリングして meeting コマンドを自動送信するスレッド"""

    def __init__(self, config: dict, recorder=None):
        self._config = config
        self._recorder = recorder
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        # 処理済みイベント ID のセット {event_id: "started" | "ended"}
        self._processed: dict[str, str] = {}
        # 直近ポーリング結果キャッシュ (ダッシュボード表示用)
        self._last_events: list[dict] = []

    def get_upcoming_events(self) -> list[dict]:
        """ダッシュボード向けに直近イベント情報を返す"""
        return self._last_events

    def get_ongoing_event_name(self) -> str | None:
        """現在時刻に進行中のイベントがあればサニタイズ済みの名前を返す。なければ None。"""
        now_utc = datetime.datetime.utcnow()
        for event in self._last_events:
            # _last_events の start/end は ISO 文字列
            try:
                start_dt = _parse_event_time({"dateTime": event["start"]}) if "T" in event.get("start", "") else None
                end_dt = _parse_event_time({"dateTime": event["end"]}) if "T" in event.get("end", "") else None
            except Exception:
                continue
            if start_dt and end_dt and start_dt <= now_utc < end_dt:
                return _sanitize_name(event.get("summary", "meeting"))
        return None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="gcal-monitor", daemon=True
        )
        self._thread.start()
        logger.info("Google Calendar モニター起動")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Google Calendar モニター停止")

    def _has_recent_speech(self, silence_seconds: int = 60) -> bool:
        """直近 silence_seconds 秒以内に transcript ファイルへの書き込みがあれば True"""
        if self._recorder is None:
            return False
        try:
            path = self._recorder.output_path
            mtime = os.path.getmtime(path)
            age = time.time() - mtime
            return age < silence_seconds
        except OSError:
            return False

    def _send_command(self, cmd: str):
        """COMMAND_FILE にコマンドを書き込む"""
        try:
            with open(COMMAND_FILE, "w", encoding="utf-8") as f:
                f.write(cmd)
            logger.info("gcal コマンド送信: %s", cmd)
        except OSError as e:
            logger.warning("gcal コマンド送信失敗: %s", e)

    def _run(self):
        credentials_file = self._config.get("gcal_credentials_file")
        if not credentials_file:
            logger.error("gcal_credentials_file が設定されていません")
            return

        credentials_file = os.path.expanduser(credentials_file)
        token_file = self._config.get("gcal_token_file") or os.path.join(DATA_DIR, "gcal_token.json")
        token_file = os.path.expanduser(token_file)
        calendar_id = self._config.get("gcal_calendar_id", "primary")
        buffer_min = int(self._config.get("gcal_buffer_minutes", 2))
        end_buffer_min = int(self._config.get("gcal_end_buffer_minutes", 1))

        try:
            creds = _get_credentials(credentials_file, token_file)
            service = _build_service(creds)
        except Exception as e:
            logger.error("Google Calendar 認証失敗: %s", e)
            return

        while not self._stop_event.is_set():
            try:
                self._poll(service, calendar_id, buffer_min, end_buffer_min)
            except Exception as e:
                logger.warning("gcal ポーリングエラー: %s", e)
            self._stop_event.wait(_POLL_INTERVAL)

    def _poll(self, service, calendar_id: str, buffer_min: int, end_buffer_min: int):
        now_utc = datetime.datetime.utcnow()
        next_poll = now_utc + datetime.timedelta(seconds=_POLL_INTERVAL)
        events = _fetch_events(service, calendar_id, now_utc)

        # ダッシュボード向けキャッシュ更新
        # 進行中・未来・処理済みのイベントのみ保持（昨日終了した未処理イベントは除外）
        self._last_events = [
            {
                "id": e.get("id", ""),
                "summary": e.get("summary", ""),
                "start": e.get("start", {}).get("dateTime", e.get("start", {}).get("date", "")),
                "end": e.get("end", {}).get("dateTime", e.get("end", {}).get("date", "")),
                "status": self._processed.get(e.get("id", ""), "pending"),
            }
            for e in events
            if (
                _parse_event_time(e.get("end", {})) is None  # 終日イベント
                or _parse_event_time(e.get("end", {})) >= now_utc  # 進行中 or 未来
                or e.get("id", "") in self._processed  # 処理済み（ended など）
            )
        ]

        for event in events:
            event_id = event.get("id", "")
            summary = event.get("summary", "meeting")
            sanitized = _sanitize_name(summary)

            start_dt = _parse_event_time(event.get("start", {}))
            end_dt = _parse_event_time(event.get("end", {}))

            if start_dt is None or end_dt is None:
                continue  # 終日イベントはスキップ

            # 「開始 buffer_min 分前」が今〜次回ポーリングの間に入るなら start_meeting
            # また、すでに進行中 (start_dt <= now < end_dt) で未処理なら即 start_meeting
            trigger_start = start_dt - datetime.timedelta(minutes=buffer_min)
            is_upcoming = now_utc <= trigger_start <= next_poll or trigger_start <= now_utc <= start_dt
            is_ongoing = start_dt <= now_utc < end_dt
            if (is_upcoming or is_ongoing) and self._processed.get(event_id) not in ("started", "ended"):
                self._send_command(f"start_meeting {sanitized}")
                self._processed[event_id] = "started"
                logger.info("会議開始検出 (%s): %s (%s)", "進行中" if is_ongoing else "予定", summary, event_id)

            # 終了トリガー: end_dt を過ぎたら end_meeting を試みる
            # ただし直近1分間に会話があれば延期（次回ポーリングで再チェック）
            trigger_end = end_dt + datetime.timedelta(minutes=end_buffer_min)
            if (now_utc <= trigger_end <= next_poll or end_dt <= now_utc <= trigger_end or now_utc > trigger_end):
                if self._processed.get(event_id) == "started":
                    if self._has_recent_speech(silence_seconds=60):
                        logger.info("会議終了延期（会話継続中）: %s (%s)", summary, event_id)
                    else:
                        self._send_command("end_meeting")
                        self._processed[event_id] = "ended"
                        logger.info("会議終了検出: %s (%s)", summary, event_id)

        # 古い処理済みエントリを掃除 (6時間以上前のものを削除)
        cutoff = now_utc - datetime.timedelta(hours=6)
        self._processed = {
            k: v for k, v in self._processed.items()
            if any(
                e.get("id") == k and (_parse_event_time(e.get("end", {})) or datetime.datetime.min) > cutoff
                for e in events
            )
        }


def run_auth(credentials_file: str, token_file: str | None = None):
    """OAuth 認証フローを実行してトークンを保存する (clerk-util gcal-auth 用)"""
    token_file = token_file or os.path.join(DATA_DIR, "gcal_token.json")
    credentials_file = os.path.expanduser(credentials_file)
    token_file = os.path.expanduser(token_file)
    creds = _get_credentials(credentials_file, token_file)
    print(f"認証完了。トークンを保存しました: {token_file}")
    return creds
