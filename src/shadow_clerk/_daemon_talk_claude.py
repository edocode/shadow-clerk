"""Shadow-clerk daemon: Claude talk mode の常駐 claude プロセス（stream-json）

AI Console（PTY）とは別に、画面を持たない claude を1本だけ常駐させる。
1行1メッセージの JSON で user 発言を送る。assistant イベントの text ブロックは届いた順に
on_text へ渡し（「ちょっと考えます」をツール実行前に話せるように）、result でターン終了を知らせる。
"""
from __future__ import annotations

import json
import logging
import subprocess
import threading
from typing import Callable

from shadow_clerk._daemon_console import sanitized_env

logger = logging.getLogger("shadow-clerk")


def build_claude_argv(config: dict, system_prompt: str) -> list[str]:
    tools = str(config.get("talk_allowed_tools") or "")
    # ユーザー設定の hooks・プラグイン・MCP は会話役に要らない。読ませると起動が重く、
    # 余計な指示がコンテキストに入る。OAuth 認証は設定ファイルではないので生きる
    argv = [str(config.get("claude_cli_path") or "claude"), "-p",
            "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config",
            "--disable-slash-commands", "--tools", tools,
            "--append-system-prompt", system_prompt]
    if tools:
        argv += ["--allowedTools", tools]
    if config.get("talk_model"):
        argv += ["--model", str(config["talk_model"])]
    return argv


class ClaudeTalkProcess:
    """stream-json で会話する常駐 claude"""

    def __init__(self, argv: list[str], workdir: str, on_text: Callable[[str], None],
                 on_turn_end: Callable[[bool], None], on_exit: Callable[[int | None], None]) -> None:
        self._argv = argv
        self._workdir = workdir
        self._on_text = on_text
        self._on_turn_end = on_turn_end
        self._on_exit = on_exit
        self._proc: subprocess.Popen[str] | None = None
        self._write_lock = threading.Lock()
        self._stopping = False

    def start(self) -> None:
        # stderr を stdout に寄せる: 別パイプにすると読まれないまま詰まって子が止まる
        self._proc = subprocess.Popen(
            self._argv, cwd=self._workdir, env=sanitized_env(), text=True, encoding="utf-8",
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1)
        threading.Thread(target=self._read_loop, name="talk-claude", daemon=True).start()
        logger.info("talk: claude 起動 (pid=%s)", self._proc.pid)

    def send(self, text: str) -> None:
        line = json.dumps({"type": "user", "message": {"role": "user", "content": text}},
                          ensure_ascii=False)
        with self._write_lock:
            if self._proc is None or self._proc.stdin is None:
                return
            try:
                self._proc.stdin.write(line + "\n")
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as e:
                logger.warning("talk: claude への送信に失敗: %s", e)

    def stop(self) -> None:
        self._stopping = True
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.close()
            proc.terminate()
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        except OSError as e:
            logger.debug("talk: claude の停止で例外: %s", e)

    def _read_loop(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        for raw in proc.stdout:
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                logger.debug("talk: claude: %s", raw.rstrip())
                continue
            if not isinstance(ev, dict):
                continue
            if ev.get("type") == "assistant":
                for block in (ev.get("message") or {}).get("content") or []:
                    text = block.get("text") if isinstance(block, dict) and block.get("type") == "text" else None
                    if isinstance(text, str) and text.strip():
                        self._on_text(text)
            elif ev.get("type") == "result":
                ok = ev.get("subtype") == "success"
                if not ok:
                    logger.warning("talk: claude のターンが失敗: %s", ev.get("subtype"))
                self._on_turn_end(ok)
        code = proc.wait()
        if not self._stopping:
            logger.warning("talk: claude が終了 (code=%s)", code)
            self._on_exit(code)
