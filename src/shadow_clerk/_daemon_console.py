"""Shadow-clerk daemon: AI アシスタントを動かす PTY セッション"""
from __future__ import annotations
import atexit
import json
import logging
import os
import threading
import time
from codecs import getincrementaldecoder
from typing import Any, Callable

import pyte

from shadow_clerk._daemon_config import load_config
from shadow_clerk._daemon_console_filter import PrivateCsiFilter
from shadow_clerk._daemon_console_pty import ConsolePty, open_console_pty
from shadow_clerk._daemon_console_render import render_rows
from shadow_clerk._daemon_constants import (
    CONSOLE_BELOW_CURSOR_ROWS,
    CONSOLE_READY_QUIET_SEC, CONSOLE_READY_TIMEOUT_SEC, CONSOLE_SUBMIT_DELAY_SEC, CONSOLE_TICK_SEC,
    CONSOLE_COLS_FILE, DEFAULT_COLS, VIRTUAL_ROWS,
)
from shadow_clerk._transcript_name import TranscriptName
from shadow_clerk.domain.ai_assistant import AiAssistantConfig
from shadow_clerk.domain.mtg_config import MtgConfig

logger = logging.getLogger("shadow-clerk")

# 親から継承すると、子の Claude Code が「親セッションの子」と誤認して
# transcript 保存を止めてしまう変数。前置き一致で落とす——将来この接頭辞で
# 変数が増えても自動で対象に入る。ANTHROPIC_* は API キー等で子に必要なので残す。
_MARKER_PREFIXES = ("CLAUDE_CODE_", "CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT")


def _load_cols() -> int:
    """前回ブラウザが決めた列数。無ければ DEFAULT_COLS

    子は会議のたびに起動し直り、デーモンも再起動する。ブラウザは幅が変わった
    ときしか列数を送らないので、覚えていないと新しい子は毎回 120 桁で描き始め、
    その履歴が「横幅が固定」に見える。
    """
    try:
        with open(CONSOLE_COLS_FILE, "r", encoding="utf-8") as f:
            return max(20, min(500, int(f.read().strip())))
    except (OSError, ValueError):
        return DEFAULT_COLS


def _save_cols(cols: int) -> None:
    try:
        with open(CONSOLE_COLS_FILE, "w", encoding="utf-8") as f:
            f.write(str(cols))
    except OSError as e:
        logger.warning("列数を保存できません: %s", e)


def sanitized_env() -> dict[str, str]:
    """親 Claude Code のセッションマーカーを除いた環境変数を返す"""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(_MARKER_PREFIXES)}
    env["TERM"] = "xterm-256color"
    # COLUMNS/LINES は設定しない。TIOCSWINSZ で伝えたサイズが唯一の正とする
    env.pop("COLUMNS", None)
    env.pop("LINES", None)
    return env


class ConsoleSession:
    """PTY を1本持ち、子プロセスの出力を pyte の長い grid に流し込む"""

    def __init__(self) -> None:
        self.screen = pyte.Screen(DEFAULT_COLS, VIRTUAL_ROWS)
        self.screen.set_mode(pyte.modes.LNM)
        self._stream = pyte.Stream(self.screen)
        self._decoder = getincrementaldecoder("utf-8")("replace")
        self._cols = _load_cols()
        self._csi_filter = PrivateCsiFilter()
        self._pty: ConsolePty | None = None
        self._reader: threading.Thread | None = None
        self._lock = threading.RLock()
        self.max_row = 0
        self._broadcast: Callable[[str, str], None] | None = None
        # 子に渡すダッシュボードの URL。ポートは CLI 引数で変えられるので、
        # スキル側に既定値を推測させず、起こす側が環境変数で教える
        self._dashboard_url: str = ""
        self._tick: threading.Thread | None = None
        self._tick_stop = threading.Event()
        self._seq = 0
        self._last_running: bool | None = None
        self._has_output = False

    # --- ライフサイクル ---

    def start(self, argv: list[str], workdir: str) -> bool:
        """PTY を開いて argv を起動する。既に走っていれば何もせず True を返す"""
        # 死んだセッション (子が自分で終了した: /exit、Ctrl-D、クラッシュ、OOM) の
        # 後始末は、ロックを持ったまま行ってはいけない。is_running() が唯一の
        # 掃除ゲートなので掃除自体 (stop()) は必要——前セッションの fd と tick
        # スレッドが後始末されないまま残り、直後に開く新しい PTY と合わせて
        # tick スレッドが2本同時に走ってしまう。ただし stop() は console-tick
        # (_emit_diff) / console-reader を join するが、両スレッドとも同じ
        # self._lock を取りに来る。_lock は RLock なのでこの関数自身の再入は
        # 素通りしてしまい気づきにくいが、join は「相手がロックを手放す」こと
        # を待つ操作であり、相手が同じロックを待って止まっている限り join は
        # 進まない。stop() はロックの外で呼び、完了してから改めてロックを
        # 取り直す
        with self._lock:
            if self.is_running():
                return True
            needs_cleanup = self._pty is not None
        if needs_cleanup:
            # stop() は self._pty が None なら何もしない冪等な操作
            self.stop()
        with self._lock:
            if self.is_running():
                return True  # stop() を待つ間に別スレッドが start() を完了させていた
            env = sanitized_env()
            if self._dashboard_url:
                env["SHADOW_CLERK_URL"] = self._dashboard_url
            # 幅は self._cols。DEFAULT_COLS で開き直してはいけない——子は会議の
            # たびに起動し直る一方、ブラウザは幅が変わったときしか列数を送らない
            # (_lastCols で重複を弾く) ので、ここで初期値に戻すと新しい子は
            # 120 桁のまま固定され、ペインの右側が空いたままになる
            pty_session = open_console_pty(argv, workdir, env, self._cols)
            if pty_session is None:
                return False
            self._pty = pty_session
            # get_console() のシングルトンは stop() 直後に再利用されうる。
            # 前セッションの grid 状態を引きずると、新しい子プロセスが
            # まだ何も出力していない段階で send_after_ready の ready 判定
            # (_has_output) が前セッションの出力で誤って通ってしまう。
            # _seq はリセットしない: クライアントは seq を順序保証に使って
            # おらず、0 に戻すと再利用/巻き戻りの余地を無駄に作るだけ
            self._has_output = False
            self.max_row = 0
            self._reset_screen()
            self._reader = threading.Thread(
                target=self._read_loop, name="console-reader", daemon=True)
            self._reader.start()
            self._tick_stop.clear()
            self._tick = threading.Thread(
                target=self._tick_loop, name="console-tick", daemon=True)
            self._tick.start()
            logger.info("AI Console 起動: %s (cwd=%s)", " ".join(argv), workdir)
            return True

    def stop(self, timeout: float = 3.0) -> None:
        """PTY セッションごと終了させる。SIGTERM → timeout 秒 → SIGKILL

        start_new_session=True で子(bash 等)をセッションリーダーにしているが、
        対話シェルはジョブ制御で `cmd &` を自分とは別の pgrp に飛ばす。
        pgrp 単位の killpg ではその孫が生き残るので、同じセッション ID を
        持つ全 pid を対象にする。

        tick スレッドの終了もここで待つ。_tick_stop は使い回しの Event
        なので、join せずに返ると次の start() の .clear() が「まだ気づいて
        いない」古いスレッドのループ判定を書き換えてしまい、新旧2本の
        tick スレッドが同時に走りかねない。self._pty を None にするのは
        必ず join より前にする: tick スレッドの最終送信 (_emit_running)
        は is_running() を見るため、実プロセスの kill (数秒かかりうる)
        を待たずとも、ここで running=false を正しく報告できる。

        reader スレッドも同様に join する。join しないと、close(fd) と
        reader 内の最後の os.read() の間に読み取り済みのチャンクが
        スレッド内に残っている場合、そのチャンクが self._stream.feed()
        で「次の start() が screen.reset() した直後」の screen に書き
        込まれ、新セッションの表示が前セッションの残骸で汚染される。
        reader は fd が閉じるまで os.read() でブロックしうるので、
        join は必ず os.close(fd) の後（先に join すると固まる）。
        取得と None 化を tick と同じくロック内で行うのは、start() 側の
        「既に走っていれば何もしない」判定と対称に保つため。
        """
        if self._pty is None:
            # Console を一度も起動していない（atexit 経由の呼び出しも含む）。
            # 後始末する対象が無いので、毎回の daemon 終了で
            # 「AI Console 停止」ログが出るのを防ぐため黙って返る
            return
        self._tick_stop.set()
        with self._lock:
            pty_session, self._pty = self._pty, None
            tick, self._tick = self._tick, None
            reader, self._reader = self._reader, None
        if tick is not None and tick.is_alive():
            tick.join(timeout=max(timeout, CONSOLE_TICK_SEC * 10))
            if tick.is_alive():
                logger.warning(
                    "tick スレッドの終了待ちがタイムアウトしました。"
                    "次の start() で二重に走る可能性があります")
        if pty_session is not None:
            pty_session.terminate(timeout)
        if reader is not None and reader.is_alive():
            reader.join(timeout=max(timeout, CONSOLE_TICK_SEC * 10))
            if reader.is_alive():
                logger.warning(
                    "reader スレッドの終了待ちがタイムアウトしました。"
                    "次の start() で旧セッションの出力が新 screen に混入する"
                    "可能性があります")
        logger.info("AI Console 停止")

    def is_running(self) -> bool:
        pty_session = self._pty
        return pty_session is not None and pty_session.is_running()

    def start_if_stopped(self, argv: list[str], workdir: str) -> tuple[bool, bool]:
        """(使える状態になったか, このコールが実際にプロセスを起こしたか) を返す。

        起動判定とプロンプト送信判定を分けて読むと、2 つの呼び出しが両方
        「自分が起動した」と信じて初期プロンプトを二重に打ち込む。
        """
        with self._lock:
            if self.is_running():
                return True, False
            return self.start(argv, workdir), True

    # --- 入出力 ---

    def write(self, data: str) -> None:
        """PTY にキー入力を書き込む"""
        pty_session = self._pty
        if pty_session is None:
            return
        try:
            pty_session.write(data.encode("utf-8"))
        except OSError as e:
            logger.warning("Console への書き込みに失敗: %s", e)

    def resize(self, cols: int) -> None:
        """列数だけ変える。行数は VIRTUAL_ROWS のまま動かさない

        grid も子と同じ幅に揃える。切り詰めで旧幅の行は右端が落ちるが、子が
        SIGWINCH を受けて ESC[H から会話ごと新しい幅で書き直すので治る。
        背の高い grid はその描き直しが grid 内で完結することを担保している。
        ここで「古い幅の写し」を残すと、その自己修復が効かなくなる。
        """
        cols = max(20, min(500, cols))
        with self._lock:
            if cols != self._cols:
                _save_cols(cols)
            self._cols = cols
            self.screen.resize(VIRTUAL_ROWS, cols)
            if self._pty is not None:
                self._pty.set_winsize(VIRTUAL_ROWS, cols)

    # --- 配信・ready 判定 ---

    def set_dashboard_url(self, url: str) -> None:
        """子プロセスに教えるダッシュボードの URL を差す"""
        self._dashboard_url = url

    def set_broadcaster(self, fn: Callable[[str, str], None] | None) -> None:
        """SSE への配信関数を差す。FileWatcher._broadcast を想定"""
        self._broadcast = fn

    def snapshot(self) -> dict[str, Any]:
        """grid 全体を返す。ページ初回ロードと再接続で使う"""
        with self._lock:
            rows = render_rows(self.screen, range(0, self.max_row + 1))
            return {
                "seq": self._seq,
                "rows": {k: v for k, v in rows.items() if v},
                "max_row": self.max_row,
                "cursor": [self.screen.cursor.y, self.screen.cursor.x],
                "running": self.is_running(),
                "full": True,
            }

    def send_after_ready(self, text: str) -> None:
        """TUI の起動を待ってから text を送る。呼び出しはブロックしない"""
        threading.Thread(
            target=self._send_after_ready_blocking, args=(text,),
            name="console-init-prompt", daemon=True).start()

    def _send_after_ready_blocking(self, text: str) -> None:
        # 固定 sleep では TUI の起動時間のばらつきを吸収できない。
        # grid が非空になってから CONSOLE_READY_QUIET_SEC 変化しなければ
        # 描画が落ち着いたとみなす。上限を過ぎたら諦めて送り、ログに残す。
        deadline = time.monotonic() + CONSOLE_READY_TIMEOUT_SEC
        quiet_since: float | None = None
        last_seq = -1
        while time.monotonic() < deadline:
            if not self.is_running():
                logger.warning("init_prompt を送る前に子プロセスが終了しました")
                return
            with self._lock:
                # max_row (cursor.y の最大値) は「非空」の代理には使えない。
                # プロンプトが1行に収まると cursor は row0 に留まったまま
                # 描画されるため、max_row==0 のままでも grid は非空になる。
                # screen.buffer も使えない: _emit_diff 自身が (子プロセスの
                # 出力とは無関係に) render_rows 経由で screen.buffer[0] を
                # 実体化させる副作用を持つため、broadcaster を差した本番
                # 構成では tick 開始からほぼ即座に非空と誤判定してしまう。
                # 子プロセスが実際に何か出力したかだけを表す _has_output を見る
                seq, empty = self._seq, not self._has_output
            if empty:
                quiet_since = None
            elif seq != last_seq:
                last_seq, quiet_since = seq, time.monotonic()
            elif quiet_since is not None and \
                    time.monotonic() - quiet_since >= CONSOLE_READY_QUIET_SEC:
                break
            time.sleep(CONSOLE_TICK_SEC)
        else:
            logger.warning("AI Console の ready 判定がタイムアウトしました。そのまま送信します")
        self._write_with_submit(text)

    def _write_with_submit(self, text: str) -> None:
        """本文と Enter を分けて送る。

        本文と CR を 1 回の os.write でまとめると、TUI (Ink 等) は読み取った
        チャンクごと入力欄に流し込み、末尾の CR を「送信」ではなく貼り付けの
        一部として吸収する——文字は入るが Enter が効かない。
        """
        body = text[:-1] if text.endswith("\r") else text
        self.write(body)
        if body is not text:
            time.sleep(CONSOLE_SUBMIT_DELAY_SEC)
            self.write("\r")

    def _tick_loop(self) -> None:
        while not self._tick_stop.is_set():
            try:
                self._emit_diff()
            except Exception as e:  # pylint: disable=broad-except
                logger.warning("Console の差分配信で例外: %s", e, exc_info=e)
            self._tick_stop.wait(CONSOLE_TICK_SEC)
        self._emit_running(force=True)

    def _extend_max_row_below_cursor(self) -> None:
        """カーソルより下に描かれた行まで max_row を伸ばす。呼び出し側でロック済み

        TUI は入力枠の下辺や "auto mode on" のヒントをカーソルより下に描く。
        max_row は cursor.y の高水位なので、そのままだと dirty の絞り込みで
        それらの行が毎回落とされ、クライアントには一度も届かない。
        pyte は reset / resize で 1 万行を dirty にするため dirty 全体は
        見に行けないので、カーソルの少し下までを窓にして拾う。
        """
        base = self.max_row
        limit = min(base + CONSOLE_BELOW_CURSOR_ROWS, VIRTUAL_ROWS - 1)
        for y in range(base + 1, limit + 1):
            if y in self.screen.dirty and any(
                    c.data.strip() for c in self.screen.buffer[y].values()):
                self.max_row = y

    def _full_payload(self) -> dict[str, Any]:
        """grid を白紙にしたことを伝えるペイロード。呼び出し側でロック済み"""
        seq = self._seq
        self._seq += 1
        return {
            "seq": seq,
            "rows": {},
            "max_row": 0,
            "cursor": [self.screen.cursor.y, self.screen.cursor.x],
            "running": self.is_running(),
            "full": True,
        }

    def _emit_diff(self) -> None:
        fn = self._broadcast
        if fn is None:
            return
        payload = None
        with self._lock:
            # pyte は reset / resize で全行 (10000 行) を dirty にする。
            # そのまま送ると初回だけ 1 万行の空ペイロードになるので、
            # 実際に書かれた範囲 (_read_loop がカーソル位置から進める max_row)
            # までに絞る。書かれていない行はクライアントも持っていない
            self.max_row = max(self.max_row, self.screen.cursor.y)
            self._extend_max_row_below_cursor()
            if self.max_row >= VIRTUAL_ROWS - 1:
                # grid の末尾に達した。pyte の Screen.index() はスクロールの
                # たびに dirty を全 10000 行に更新するため、ここで放置すると
                # 出力のある毎 tick (10Hz) で 1 万行の render_rows が走り、
                # 録音・文字起こしと同じ GIL の下で CPU を奪い合う。
                # end_meeting でセッションを止めない設計上、この境界は
                # 1 会議ではなくデーモンの寿命ぶんの出力で踏まれうる。
                # spec は「先頭が失われることを許容する」と明記しているので、
                # grid をリセットして full snapshot から再開する
                # (スクロールバックは失われる)
                logger.info(
                    "AI Console の grid が VIRTUAL_ROWS(%d) に達したためリセットします",
                    VIRTUAL_ROWS)
                self._reset_screen()
                self.max_row = 0
                self.screen.dirty.clear()
                payload = self._full_payload()
            else:
                dirty = sorted(y for y in self.screen.dirty if y <= self.max_row)
                self.screen.dirty.clear()
                if dirty:
                    payload = {
                        "seq": self._seq,
                        "rows": render_rows(self.screen, dirty),
                        "max_row": self.max_row,
                        "cursor": [self.screen.cursor.y, self.screen.cursor.x],
                        "running": self.is_running(),
                    }
                    self._seq += 1
        if payload is not None:
            fn("console", json.dumps(payload, ensure_ascii=False))
        self._emit_running()

    def emit_auto_started(self) -> None:
        """自動起動であることをクライアントに一度だけ知らせる"""
        fn = self._broadcast
        if fn is not None:
            fn("console", json.dumps(
                {"running": True, "status_only": True, "auto": True}))

    def _emit_running(self, force: bool = False) -> None:
        """running の変化だけを別途知らせる。差分が無いときも状態は伝わる"""
        fn = self._broadcast
        if fn is None:
            return
        running = self.is_running()
        if not force and running == self._last_running:
            return
        self._last_running = running
        fn("console", json.dumps({"running": running, "status_only": True}))

    # --- 内部 ---

    def _reset_screen(self) -> None:
        """grid を初期化する。screen.reset() は LNM モードも消すので入れ直す"""
        self.screen.reset()
        if self.screen.columns != self._cols:
            self.screen.resize(VIRTUAL_ROWS, self._cols)
        self.screen.set_mode(pyte.modes.LNM)
        self._csi_filter.reset()

    def _read_loop(self) -> None:
        pty_session = self._pty
        while pty_session is not None:
            chunk = pty_session.read(65536)
            if not chunk:
                break  # 子が終了して端末が閉じた
            text = self._csi_filter.feed(self._decoder.decode(chunk))
            if not text:
                continue
            with self._lock:
                self._stream.feed(text)
                self.max_row = max(self.max_row, self.screen.cursor.y)
                self._has_output = True
        logger.info("AI Console の子プロセスが終了しました")


_console: ConsoleSession | None = None
_console_lock = threading.Lock()


def get_console() -> ConsoleSession:
    """プロセス内で唯一の ConsoleSession を返す。PTY は1本しか立てない

    start_new_session=True で起こす子は端末からも切り離されており、
    daemon が異常終了する経路（main() の finally を通らない未捕捉例外や
    シグナルなど）では手で pgrep して殺すしかない対話プロセスとして残る。
    シングルトンを作った最初の1回だけ atexit.register(stop) しておけば、
    そうした経路の多くを atexit の通常インタプリタ終了フックで拾える。
    main() の finally でも get_console().stop() を呼んでおり二重登録に
    なるが、stop() は self._pty が None なら何もしない冪等な操作なので
    実害はない（atexit 自体は SIGKILL では走らないため、それでも拾い
    きれない経路が残る点は README に記載する）。
    """
    global _console
    with _console_lock:
        if _console is None:
            _console = ConsoleSession()
            atexit.register(_console.stop)
        return _console


def request_summary_from_console(transcript_path: str) -> bool:
    """走っている AI コンソールに議事録の作成を頼む。

    スキルは「議事録の作成はユーザーの指示を待つ」設計だが、その門は
    アシスタントが勝手に終了を判断して作り始めるのを防ぐためのもの。
    shadow-clerk は end_meeting を確かに知っているので、ここから送る依頼は
    ユーザーの指示にあたる。

    コンソールが走っていなければ False を返す。呼び出し側は従来の LLM 要約に
    落とすこと——落とさないと議事録が 1 つも出来ない。
    """
    console = get_console()
    if not console.is_running():
        return False
    tn = TranscriptName.parse(os.path.basename(transcript_path))
    if tn is None:
        return False
    out = os.path.join(os.path.dirname(transcript_path), tn.summary_filename)
    prompt = (f"会議が終了しました。{transcript_path} の議事録を作成し、"
              f"{out} に書いてください。")
    logger.info("AI コンソールに議事録の作成を依頼します: %s", out)
    console.send_after_ready(prompt + "\r")
    return True


def start_console_for(transcript_path: str, auto: bool = False,
                      send_prompt: bool = True) -> bool:
    """transcript に対して AI アシスタントを起動し、初期プロンプトを送る。

    既に走っていれば起動はせず、初期プロンプトだけを送る（セッションを使い回す）。

    `send_prompt=False` は端末を出すだけで何も打ち込まない。前のセッションを
    `/resume` で拾い直したいときに要る——初期プロンプトが入ると、拾う前に
    新しい会話が始まってしまう。

    ここは HTTP ハンドラではなくオーケストレーション処理なので
    _daemon_console.py に置く。以前はダッシュボードの HTTP 層
    (_daemon_dashboard_ops_console.py) に置かれており、録音経路
    (_daemon_recorder_command.py) が録音とは無関係な HTTP ハンドラ層に
    依存する層の逆転が起きていた。加えて _daemon_log_buffer.py は同じ
    関数を _poll() の中で遅延 import しており(こちらは advice/analysis の
    ファイル名ヘルパのためで、循環 import になるため今もそのまま)、
    同じ関数の import 方針がモジュールごとに矛盾していた。
    ConsoleSession 自体(および pyte)への依存は録音がこの機能を呼び出す
    以上もともと避けられない
    """
    config = load_config()
    ai = AiAssistantConfig.from_config(config)
    meeting = ""
    if transcript_path:
        tn = TranscriptName.parse(os.path.basename(transcript_path))
        meeting = (tn.meeting_name or "") if tn else ""
    workdir = ai.resolve_workdir(MtgConfig.load().resolve_workdir(meeting))

    console = get_console()
    ok, _started = console.start_if_stopped(ai.argv(), workdir)
    if not ok:
        return False
    if auto:
        # 自動起動はユーザーが見ていない場所で始まる。ダッシュボードが
        # 議事録ペインと AI コンソールを自分で開けるよう、手動起動と
        # 区別できる形で知らせる
        console.emit_auto_started()
    # 出力言語は翻訳先言語に合わせる。スキルは transcript の言語ではなく
    # ユーザーが読みたい言語で書くべきで、その設定は既に config にある
    prompt = "" if not send_prompt else ai.resolve_init_prompt(
        transcript_path, meeting, str(config.get("translate_language") or ""))
    if not prompt:
        return True
    # _started の真偽に関わらず常に send_after_ready を通す。
    # 「起動済みなら即 write」にすると、TUI がまだ起動中に届いた2回目の
    # 呼び出し (連打・auto_analyze 直後の発話コマンド・start_meeting の
    # 重複) が起動途中の端末にプロンプトを打ち込んで消してしまう。
    # 既に ready なセッションでは _has_output が true なので、
    # quiet 判定はほぼ即座 (CONSOLE_READY_QUIET_SEC 秒) に収束する
    # セッションを使い回した場合 start() は何も記録しないので、ここで残す。
    # これが無いと「会議開始と同時に分析が始まったのか」を確かめる手段が
    # ログに一つも無くなる（実際に分からないと指摘された）
    logger.info("AI アシスタントに初期プロンプトを送ります: %s (%s)",
                prompt, "新規起動" if _started else "既存セッションを再利用")
    console.send_after_ready(prompt + "\r")
    return True
