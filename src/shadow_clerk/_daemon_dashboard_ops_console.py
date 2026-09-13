"""Shadow-clerk daemon: ダッシュボード AI Console エンドポイント"""
# pylint: disable=duplicate-code  # POST ボディ解析の定型は各ハンドラで共通形
from __future__ import annotations
import json
import logging
import os
import re
from urllib.parse import urlparse, parse_qs

from shadow_clerk._daemon_console import get_console, start_console_for
from shadow_clerk._daemon_constants import FORBID_ANALYZE_FILE, MISHEARD_FILE
from shadow_clerk._daemon_dashboard_base import is_localhost_client, is_same_origin_request
from shadow_clerk._markdown import render_markdown
from shadow_clerk._transcript_name import TranscriptName
from shadow_clerk.domain import misheard
from shadow_clerk.domain.forbid_analyze import ForbidAnalyze
from shadow_clerk.domain.meeting_config import MeetingConfig

logger = logging.getLogger("shadow-clerk")

__all__ = ["start_console_for", "_DashboardHandlerConsoleOps"]

# 1 リクエストで送れるキー入力の上限。貼り付けを通しつつ暴走を止める
_MAX_INPUT_CHARS = 8192


class _DashboardHandlerConsoleOps:
    """AI Console の操作（ミックスイン）"""

    def _console_body(self) -> dict | None:
        """localhost 判定・Origin 判定・JSON ボディの読み取り。不正なら None を返して応答済みにする"""
        client = self.client_address[0] if self.client_address else ""
        if not is_localhost_client(self.client_address):
            logger.warning("console: 拒否 (client=%s)", client)
            self._send_json({"status": "error", "message": "console API is localhost only"})
            return None
        if not is_same_origin_request(self.headers):
            # client_address ベースの localhost 判定は、ユーザー自身が開いた
            # 任意のページからのクロスオリジン fetch に対しては無力
            # (ブラウザから見れば送信元は常にこのマシンの 127.0.0.1)。
            # PTY への任意のキー入力送信 (=任意コマンド実行) を許すエンド
            # ポイントなので、Origin ヘッダで自分自身へのリクエストかを見る
            logger.warning("console: 拒否 (cross-origin, origin=%s)",
                           self.headers.get("Origin"))
            self._send_json({"status": "error", "message": "cross-origin request rejected"})
            return None
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            self._send_json({"status": "error", "message": "invalid request body"})
            return None
        if not isinstance(data, dict):
            self._send_json({"status": "error", "message": "request body must be a JSON object"})
            return None
        return data

    def _serve_console(self) -> None:
        """GET /api/console — grid 全体を返す（初回ロード・再接続用）

        grid には会議アシスタントスキルの出力やツールの標準出力がそのまま載りうる。
        ダッシュボードを外部公開する運用でも、この読み取りだけは
        書き込み系エンドポイントと同じく localhost に限る
        (Origin チェックは読み取り専用の GET には不要)
        """
        if not is_localhost_client(self.client_address):
            client = self.client_address[0] if self.client_address else ""
            logger.warning("console: 拒否 (client=%s)", client)
            self._send_json({"status": "error", "message": "console API is localhost only"})
            return
        self._send_json(get_console().snapshot())

    def _start_console(self) -> None:
        """POST /api/console/start — アシスタントを起動して初期プロンプトを送る。

        `{"prompt": false}` なら端末を出すだけで何も打ち込まない (`/resume` 用)。
        """
        data = self._console_body()
        if data is None:
            return
        transcript = data.get("transcript")
        # ダッシュボードはファイル名しか持っていないが、スキルにはフルパスが要る。
        # ディレクトリを跨ぐ指定は受けず、出力ディレクトリ内に解決する。
        # os.path.basename() だけでは ".." / "." を弾けない
        # (os.path.basename("..") == ".." が True になるため) ので、
        # transcript ファイル名として正しくパースできることに加え、
        # _generated_path と同じく basename と一致すること (会議名グループの
        # [^.]+ はスラッシュを許すため) も要求する
        if (isinstance(transcript, str) and os.path.basename(transcript) == transcript
                and TranscriptName.parse(transcript) is not None):
            transcript = os.path.join(self.recorder._output_dir, transcript)
        else:
            transcript = self.recorder.output_path
        ok = start_console_for(transcript, send_prompt=data.get("prompt") is not False)
        self._send_json({"status": "ok" if ok else "error",
                         "running": get_console().is_running()})

    def _stop_console(self) -> None:
        """POST /api/console/stop — プロセスグループごと終了させる"""
        if self._console_body() is None:
            return
        get_console().stop()
        self._send_json({"status": "ok", "running": False})

    def _console_input(self) -> None:
        """POST /api/console/input — キー入力を PTY に書き込む"""
        data = self._console_body()
        if data is None:
            return
        payload = data.get("data")
        if not isinstance(payload, str):
            self._send_json({"status": "error", "message": "data must be a string"})
            return
        if len(payload) > _MAX_INPUT_CHARS:
            self._send_json({"status": "error", "message": "data too large"})
            return
        get_console().write(payload)
        self._send_json({"status": "ok"})

    def _console_resize(self) -> None:
        """POST /api/console/resize — 列数だけ変える（行数は固定）"""
        data = self._console_body()
        if data is None:
            return
        try:
            cols = int(data.get("cols", 0))
        except (TypeError, ValueError):
            self._send_json({"status": "error", "message": "cols must be an integer"})
            return
        get_console().resize(cols)
        self._send_json({"status": "ok", "cols": get_console().screen.columns})

    def _generated_path(self) -> tuple[str, str] | None:
        """クエリの file から (advice 名, analysis 名) を解決する。不正なら None"""
        query = parse_qs(urlparse(self.path).query)
        name = (query.get("file") or [""])[0] or os.path.basename(
            self.recorder.output_path)
        if os.path.basename(name) != name:
            # ディレクトリを跨ぐ指定は受けない
            logger.warning("生成物の取得: 不正なファイル名 %r", name)
            return None
        tn = TranscriptName.parse(name)
        if tn is None:
            return None
        return tn.advice_filename, tn.analysis_filename

    def _serve_generated(self, index: int) -> None:
        """生成物 (Markdown) を HTML に起こして返す。

        advice も analysis もアシスタントが書く Markdown なので、読みやすさの
        ために HTML で配る。生 HTML はレンダラ側で実体参照に落ちる
        (_markdown.render_markdown 参照)。
        """
        names = self._generated_path()
        if names is None:
            self._send_json({"file": "", "html": ""})
            return
        path = os.path.join(self.recorder._output_dir, names[index])
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError:
            text = ""
        self._send_json({"file": names[index], "html": render_markdown(text)})

    def _serve_generated_paths(self) -> None:
        """GET /api/generated — transcript に対応する生成物のパスを返す。

        命名規則を知っているのは TranscriptName だけにしたい。スキル側が
        `summary-<stem>.md` のような規則を自前で持つと、片方だけ変えたときに
        黙ってずれる（会議のリネームで実際に起きうる）。パスはここで解決して
        絶対パスで渡し、スキルはそれをそのまま使う。
        """
        if not is_localhost_client(self.client_address):
            self._send_json({"status": "error",
                             "message": "generated paths API is localhost only"})
            return
        query = parse_qs(urlparse(self.path).query)
        name = (query.get("file") or [""])[0] or os.path.basename(
            self.recorder.output_path)
        tn = None if os.path.basename(name) != name else TranscriptName.parse(name)
        if tn is None:
            self._send_json({"status": "error", "message": "not a transcript filename"})
            return
        out_dir = self.recorder._output_dir
        paths = {
            "transcript": os.path.join(out_dir, tn.filename),
            "summary": os.path.join(out_dir, tn.summary_filename),
            "advice": os.path.join(out_dir, tn.advice_filename),
            "analysis": os.path.join(out_dir, tn.analysis_filename),
        }
        self._send_json({
            "status": "ok",
            "dir": out_dir,
            "meeting": tn.meeting_name or "",
            **paths,
            "exists": {k: os.path.isfile(v) for k, v in paths.items()},
        })

    def _serve_advice(self) -> None:
        """GET /api/advice — 未解決の提案（全文）"""
        self._serve_generated(0)

    def _serve_analysis(self) -> None:
        """GET /api/analysis — 確定した事実（全文）"""
        self._serve_generated(1)

    def _serve_forbid_analyze(self) -> None:
        """GET /api/forbid-analyze — AI 分析の対象外にする話題"""
        fa = ForbidAnalyze.load()
        self._send_json({"status": "ok", "path": FORBID_ANALYZE_FILE,
                         "items": list(fa.items)})

    def _save_forbid_analyze(self) -> None:
        """POST /api/forbid-analyze — 一覧をまるごと置き換える"""
        data = self._console_body()
        if data is None:
            return
        fa = ForbidAnalyze.from_items(data.get("items"))
        if not fa.save():
            self._send_json({"status": "error", "message": "failed to save"})
            return
        self._send_json({"status": "ok", "items": list(fa.items)})

    def _serve_misheard(self) -> None:
        """GET /api/misheard — 聞き間違い候補の一覧"""
        self._send_json({
            "status": "ok", "path": MISHEARD_FILE,
            "entries": [{"actual": e.actual, "heard": e.heard, "note": e.note}
                        for e in misheard.load()],
        })

    def _save_misheard(self) -> None:
        """POST /api/misheard — まだ無い対だけを足す（置き換えではない）"""
        data = self._console_body()
        if data is None:
            return
        added = misheard.append(data.get("entries"))
        self._send_json({"status": "ok",
                         "added": [{"actual": e.actual, "heard": e.heard,
                                    "note": e.note} for e in added]})

    def _serve_meeting_config(self) -> None:
        """GET /api/meeting-config — 会議ごとの workdir 設定"""
        cfg = MeetingConfig.load()
        self._send_json({
            "path": cfg.path,
            "default_workdir": cfg.resolve_workdir(""),
            "rules": [{"pattern": r.pattern, "workdir": r.workdir} for r in cfg.rules()],
        })

    def _save_meeting_config(self) -> None:
        """POST /api/meeting-config — 1 ルールの追加・更新・削除

        old_pattern が指定されていれば、同じ読み込みの上で先にそのルールを
        削除してから upsert/delete する。パターンをリネームする場合、
        「削除 POST → upsert POST」の2リクエストに分けると、2本目が失敗
        (設定ディレクトリが書けない、デーモン再起動中) したときに古いルールが
        消えたまま新しいものが書かれず、ユーザーがマッピングを黙って失う。
        1 リクエスト・1 回の load→mutate→save にまとめることで、
        この経路については save() 前後の競合も閉じる
        """
        data = self._console_body()
        if data is None:
            return
        pattern = data.get("pattern")
        if not isinstance(pattern, str) or not pattern.strip():
            self._send_json({"status": "error", "message": "pattern is required"})
            return
        pattern = pattern.strip()
        try:
            re.compile(pattern)
        except re.error as e:
            # 壊れたパターンを書くとスキル側の照合も壊れるので、保存前に弾く
            self._send_json({"status": "error", "message": f"invalid pattern: {e}"})
            return
        old_pattern = data.get("old_pattern")
        cfg = MeetingConfig.load()
        if isinstance(old_pattern, str) and old_pattern.strip() and old_pattern.strip() != pattern:
            cfg.remove(old_pattern.strip())
        if data.get("delete"):
            cfg.remove(pattern)
        else:
            workdir = data.get("workdir")
            cfg.upsert(pattern, workdir.strip() if isinstance(workdir, str) else "")
        try:
            path = cfg.save()
        except OSError as e:
            logger.warning("会議設定の保存に失敗: %s", e)
            self._send_json({"status": "error", "message": str(e)})
            return
        logger.info("会議設定を更新: %s (%s)", pattern, path)
        self._send_json({"status": "ok", "path": path})
