"""Shadow-clerk: Google Calendar 連携モニター

設定が有効な場合、Google Calendar のイベントを定期ポーリングし、
開始・終了時刻に応じて start_meeting / end_meeting コマンドを自動送信する。

依存: google-auth-oauthlib, google-api-python-client
  uv sync --extra gcal
"""
from __future__ import annotations
import datetime
import logging
import os
import threading
import time
from typing import Any

from shadow_clerk import DATA_DIR
from shadow_clerk._transcript_name import sanitize_meeting_name as _sanitize_name

logger = logging.getLogger("shadow-clerk.gcal")

# Google Calendar API スコープ (読み取り専用)
_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# ポーリング間隔 (秒)
_POLL_INTERVAL = 60


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


def _extract_attendees(event: dict) -> list[str]:
    """イベントから参加予定者（表示名）を抽出する。

    - responseStatus == 'declined' は除外（明示的に辞退した人のみ）
    - resource（会議室など）は除外
    - 表示名優先、なければメールのローカル部のみ使用（@以降は記録しない）
    - 重複は除去、元の順序を保持
    """
    result: list[str] = []
    seen: set[str] = set()
    for a in event.get("attendees", []) or []:
        if a.get("responseStatus") == "declined":
            continue
        if a.get("resource"):
            continue
        name = (a.get("displayName") or "").strip()
        if not name:
            email = a.get("email") or ""
            name = email.split("@", 1)[0] if "@" in email else email
            name = name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


def _parse_event_time(event_time: dict) -> datetime.datetime | None:
    """イベントの start/end 時刻を UTC-naive datetime に変換する"""
    if "dateTime" in event_time:
        dt_str = event_time["dateTime"]
        # タイムゾーンオフセットを除去して UTC naive にする
        try:
            dt = datetime.datetime.fromisoformat(dt_str)
            # offset-aware → UTC naive
            if dt.tzinfo is not None:
                st = dt.utctimetuple()
                dt = datetime.datetime(st[0], st[1], st[2], st[3], st[4], st[5])
            return dt
        except ValueError:
            return None
    return None  # 終日イベントはスキップ


class GCalMonitor:
    """Google Calendar を定期ポーリングして meeting コマンドを自動送信するスレッド"""

    def __init__(self, config: dict[str, Any], recorder: Any = None) -> None:
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

    def _find_ongoing_event(self) -> dict | None:
        """現在時刻に進行中のイベントを返す（_last_events から）。"""
        now_utc = datetime.datetime.utcnow()
        for event in self._last_events:
            try:
                start_dt = _parse_event_time({"dateTime": event["start"]}) if "T" in event.get("start", "") else None
                end_dt = _parse_event_time({"dateTime": event["end"]}) if "T" in event.get("end", "") else None
            except Exception:
                continue
            if start_dt and end_dt and start_dt <= now_utc < end_dt:
                return event
        return None

    def get_ongoing_event_name(self) -> str | None:
        """現在時刻に進行中のイベントがあればサニタイズ済みの名前を返す。なければ None。"""
        event = self._find_ongoing_event()
        if event is None:
            return None
        return _sanitize_name(event.get("summary", "meeting"))

    def get_ongoing_event_attendees(self) -> list[str]:
        """現在進行中のイベントの参加予定者リストを返す。進行中イベントがなければ空リスト。"""
        event = self._find_ongoing_event()
        if event is None:
            return []
        return list(event.get("attendees") or [])

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="gcal-monitor", daemon=True
        )
        self._thread.start()
        logger.info("Google Calendar モニター起動")

    def stop(self) -> None:
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
        if self._recorder is None:
            logger.warning("gcal コマンド送信失敗: recorder 未初期化")
            return
        logger.info("gcal コマンド送信: %s", cmd)
        self._recorder._execute_command(cmd)

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

    def _another_meeting_ongoing(self, events: list, exclude_id: str,
                                 now_utc: datetime.datetime, end_buffer_min: int) -> bool:
        """exclude_id 以外に「start_meeting 送信済みで終了時刻が未来」のイベントがあるか。

        start_meeting は開始 buffer 分前に先行送信されるため、開始時刻ではなく
        「started 済みか」で判定する（現在のセッションはそのイベントのもの）。
        """
        for e in events:
            eid = e.get("id", "")
            if eid == exclude_id or self._processed.get(eid) != "started":
                continue
            en = _parse_event_time(e.get("end", {}))
            if en is not None and now_utc < en + datetime.timedelta(minutes=end_buffer_min):
                return True
        return False

    def _poll(self, service, calendar_id: str, buffer_min: int, end_buffer_min: int):
        now_utc = datetime.datetime.utcnow()
        next_poll = now_utc + datetime.timedelta(seconds=_POLL_INTERVAL)
        # 本日の全予定を表示するため time_max を今日の終わり（UTC翌日0時）まで拡張
        today_start_utc = datetime.datetime(now_utc.year, now_utc.month, now_utc.day)
        end_of_today_utc = today_start_utc + datetime.timedelta(days=1)
        lookahead_minutes = max(120, int((end_of_today_utc - now_utc).total_seconds() / 60))
        events = _fetch_events(service, calendar_id, now_utc, lookahead_minutes)

        # ダッシュボード向けキャッシュ更新
        # 本日の全イベント（開始済み含む）＋未来・処理済みを保持
        self._last_events = [
            {
                "id": e.get("id", ""),
                "summary": e.get("summary", ""),
                "start": e.get("start", {}).get("dateTime", e.get("start", {}).get("date", "")),
                "end": e.get("end", {}).get("dateTime", e.get("end", {}).get("date", "")),
                "status": self._processed.get(e.get("id", ""), "pending"),
                "attendees": _extract_attendees(e),
            }
            for e in events
            if (
                (end_t := _parse_event_time(e.get("end", {}))) is None  # 終日イベント
                or end_t >= now_utc  # 進行中 or 未来
                or e.get("id", "") in self._processed  # 処理済み（ended など）
                or (  # 本日開始済みの過去イベント
                    (st := _parse_event_time(e.get("start", {}))) is not None
                    and st >= today_start_utc
                )
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
                    if self._another_meeting_ongoing(events, event_id, now_utc, end_buffer_min):
                        # back-to-back 会議: 後続会議の start_meeting で現在のセッションは
                        # 既に切り替わっている。引数なし end_meeting を送ると後続会議の
                        # セッションを誤終了させるため、送信せず ended 扱いにする
                        self._processed[event_id] = "ended"
                        logger.info("会議終了 (後続会議が進行中のため end_meeting 送信なし): %s (%s)",
                                    summary, event_id)
                    elif self._has_recent_speech(silence_seconds=60):
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


def run_auth(credentials_file: str, token_file: str | None = None) -> Any:
    """OAuth 認証フローを実行してトークンを保存する (clerk-util gcal-auth 用)"""
    token_file = token_file or os.path.join(DATA_DIR, "gcal_token.json")
    credentials_file = os.path.expanduser(credentials_file)
    token_file = os.path.expanduser(token_file)
    creds = _get_credentials(credentials_file, token_file)
    print(f"認証完了。トークンを保存しました: {token_file}")
    return creds
