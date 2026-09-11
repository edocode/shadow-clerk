"""Windows でも起動できる形になっているかの検証

実行: uv run python tests/test_windows_port.py
Linux 上で走らせる。POSIX 専用モジュールを塞いだ別プロセスで import を試し、
ConPTY 側は偽の PtyProcess を挿して振る舞いだけを見る。
"""
from __future__ import annotations
import ast
import os
import subprocess
import sys
import tempfile

DATA = os.path.join(tempfile.gettempdir(), "shadow-clerk-winport-test")
os.makedirs(DATA, exist_ok=True)
os.environ.setdefault("SHADOW_CLERK_DATA_DIR", DATA)

from shadow_clerk import _daemon_console_pty as pty_mod  # noqa: E402

results: list[bool] = []

#: Windows に存在しない標準ライブラリと Linux 専用の拡張
POSIX_ONLY = {"pty", "termios", "fcntl", "grp", "pwd", "tty", "resource",
              "syslog", "evdev"}
SRC = os.path.join(os.path.dirname(__file__), "..", "src", "shadow_clerk")


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def test_no_posix_only_module_imports_at_top_level() -> None:
    """トップレベルで import すると、Windows では読み込んだ時点で落ちる。

    使ってよいが、**関数の中に閉じ込める**。ここが崩れると
    「Windows で起動しない」に一直線なので、木を歩いて押さえる。
    """
    offenders: list[str] = []
    for name in sorted(os.listdir(SRC)):
        if not name.endswith(".py"):
            continue
        tree = ast.parse(open(os.path.join(SRC, name), encoding="utf-8").read())
        for node in tree.body:                      # トップレベルのみ
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module.split(".")[0]]
            for m in mods:
                if m in POSIX_ONLY:
                    offenders.append(f"{name}:{node.lineno} {m}")
    check("POSIX 専用モジュールをトップレベルで import していない",
          not offenders, ", ".join(offenders))


def test_imports_with_posix_modules_blocked() -> None:
    """POSIX 専用を塞いだ別プロセスで、デーモンと CLI が読み込めること"""
    code = (
        "import sys\n"
        f"for m in {sorted(POSIX_ONLY)!r}:\n"
        "    sys.modules[m] = None\n"
        "import shadow_clerk.clerk_daemon\n"
        "import shadow_clerk.clerk_util\n"
        "print('ok')\n")
    p = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, timeout=120)
    check("塞いでも import できる", p.returncode == 0 and "ok" in p.stdout,
          (p.stderr or "").strip().splitlines()[-1] if p.stderr else "")


class _FakePtyProcess:
    """pywinpty の PtyProcess のうち、使う分だけを真似る"""

    def __init__(self) -> None:
        self.written: list[str] = []
        self.size: tuple[int, int] | None = None
        self.alive = True
        self.forced: bool | None = None
        self.out = "こんにちは"

    def read(self, size: int) -> str:
        out, self.out = self.out[:size], self.out[size:]
        if not out:
            raise EOFError
        return out

    def write(self, text: str) -> None:
        self.written.append(text)

    def setwinsize(self, rows: int, cols: int) -> None:
        self.size = (rows, cols)

    def isalive(self) -> bool:
        return self.alive

    def terminate(self, force: bool = False) -> None:
        self.forced = force
        self.alive = False


def test_windows_pty_translates_to_bytes() -> None:
    """上位は bytes しか知らない。pywinpty は str なので境界で戻す"""
    fake = _FakePtyProcess()
    pty = pty_mod.WindowsConsolePty(fake)
    check("読みは bytes", pty.read(64) == "こんにちは".encode("utf-8"),
          repr(pty.read(64)))
    pty.write("あ\r".encode("utf-8"))
    check("書きは str に戻して渡す", fake.written == ["あ\r"], str(fake.written))
    check("端が尽きたら空を返す(EOF を例外にしない)", pty.read(64) == b"")


def test_windows_pty_lifecycle() -> None:
    fake = _FakePtyProcess()
    pty = pty_mod.WindowsConsolePty(fake)
    pty.set_winsize(10000, 90)
    check("大きさが擬似コンソールに届く", fake.size == (10000, 90), str(fake.size))
    check("生きている", pty.is_running())
    pty.terminate(1.0)
    check("止めたら死ぬ", not pty.is_running())
    check("子ごと落とす", fake.forced is True, str(fake.forced))
    pty.terminate(1.0)
    check("二度目の terminate で落ちない(冪等)", not pty.is_running())


def test_backend_is_chosen_by_platform() -> None:
    """Windows では ConPTY、それ以外は pty.openpty"""
    fake = _FakePtyProcess()
    spawned: dict = {}

    class _Spawner:
        @staticmethod
        def spawn(argv, cwd=None, env=None, dimensions=None):
            spawned.update({"argv": argv, "cwd": cwd, "dimensions": dimensions})
            return fake

    sys.modules["winpty"] = type("m", (), {"PtyProcess": _Spawner})()
    orig = pty_mod.IS_WINDOWS
    pty_mod.IS_WINDOWS = True
    try:
        got = pty_mod.open_console_pty(["claude"], "C:\\work", {"TERM": "x"}, 90)
    finally:
        pty_mod.IS_WINDOWS = orig
        del sys.modules["winpty"]
    check("Windows では ConPTY を開く",
          isinstance(got, pty_mod.WindowsConsolePty), type(got).__name__)
    check("行数は仮想 grid の高さ、列数は覚えている幅",
          spawned.get("dimensions") == (pty_mod.VIRTUAL_ROWS, 90),
          str(spawned.get("dimensions")))
    check("起動ディレクトリを渡す", spawned.get("cwd") == "C:\\work",
          str(spawned.get("cwd")))

    got = pty_mod.open_console_pty(["true"], os.getcwd(), dict(os.environ), 90)
    check("POSIX では pty.openpty を使う",
          isinstance(got, pty_mod.PosixConsolePty), type(got).__name__)
    if got is not None:
        got.terminate(1.0)


def test_missing_pywinpty_is_reported_not_raised() -> None:
    """入っていなくても daemon 全体は落とさない。AI Console だけ諦める"""
    orig = pty_mod.IS_WINDOWS
    pty_mod.IS_WINDOWS = True
    sys.modules["winpty"] = None    # import すると ImportError になる
    try:
        got = pty_mod.open_console_pty(["claude"], ".", {}, 90)
    finally:
        pty_mod.IS_WINDOWS = orig
        del sys.modules["winpty"]
    check("None を返す(例外を投げない)", got is None, repr(got))


def test_daemonize_does_not_fork_on_windows() -> None:
    """Windows に fork は無い。分離して起こし直す道が要る"""
    src = open(os.path.join(SRC, "_daemon_main.py"), encoding="utf-8").read()
    body = src[src.index("def _daemonize() -> None:"):]
    body = body[:body.index("\ndef ", 1)]
    check("fork の前に win32 で分岐する",
          body.index('sys.platform == "win32"') < body.index("os.fork()"), "")
    win = src[src.index("def _daemonize_windows"):src.index("def _daemonize()")]
    check("DETACHED で起こし直す", "DETACHED_PROCESS" in win, "")
    # 目印が無いと、起こした子がまた子を起こして無限に増える
    check("起こし直された側は二度と起こさない", "_DAEMONIZED_ENV" in win, "")
    check("凍結された exe でも自分を起こせる", 'getattr(sys, "frozen"' in win, "")


def test_spec_collects_the_packages_that_ship_data() -> None:
    """PyInstaller はコード中の import しか追わない。

    DLL とデータファイルは spec で明示的に集める必要があり、抜けると
    **ビルドは通って実行時に落ちる**。依存を足したときに気づけるよう、
    データを持つものが spec に並んでいることをここで押さえる。
    """
    spec_path = os.path.join(os.path.dirname(__file__), "..", "packaging",
                             "shadow-clerk.spec")
    check("spec がある", os.path.exists(spec_path), spec_path)
    if not os.path.exists(spec_path):
        return
    spec = open(spec_path, encoding="utf-8").read()
    for pkg in ("ctranslate2", "av", "faster_whisper", "langdetect",
                "sounddevice", "pywinpty", "pyaudiowpatch", "tokenizers",
                # ReazonSpeech。sherpa_onnx は lib/ に onnxruntime の DLL を抱える
                "sherpa_onnx", "reazonspeech.k2.asr"):
        check(f"spec が {pkg} を集める", f'"{pkg}"' in spec, "")
    check("2 つの実行ファイルを作る",
          "clerk-daemon" in spec and "clerk-util" in spec, "")
    # torch を入れると配布物が数 GB になる。spell-check extra だけの依存
    check("重量級の任意依存を除く", "torch" in spec and "_EXCLUDES" in spec, "")
    check("クロスコンパイルできないことを書いてある",
          "クロスコンパイル" in spec, "")
    # 同梱フックは copy_metadata('webrtcvad') を呼ぶが、使っているのは
    # webrtcvad-wheels。差し替えないとビルドが途中で止まる
    check("同梱フックを差し替える hookspath を渡す", "hookspath=_HOOKS" in spec, "")
    hook = os.path.join(os.path.dirname(spec_path), "hooks", "hook-webrtcvad.py")
    check("差し替えフックがある", os.path.exists(hook), hook)
    if os.path.exists(hook):
        check("正しい配布名を渡す",
              "webrtcvad-wheels" in open(hook, encoding="utf-8").read(), "")


def test_readme_documents_the_build() -> None:
    """spec の場所と「クロスコンパイルできない」は README から辿れること。

    Linux で Windows 版を作ろうとして詰まるのが最初の躓きどころなので、
    spec 冒頭のコメントだけでなく README にも置く。
    """
    root = os.path.join(os.path.dirname(__file__), "..")
    for name, heading, cross in (
            ("README.md", "## Building a standalone binary",
             "does not cross-compile"),
            ("README.ja.md", "## スタンドアロンバイナリのビルド",
             "クロスコンパイルしない")):
        doc = open(os.path.join(root, name), encoding="utf-8").read()
        check(f"{name} にビルドの節がある", heading in doc, "")
        check(f"{name} がクロスコンパイル不可を書いている", cross in doc, "")
        check(f"{name} が spec の場所を書いている",
              "packaging/shadow-clerk.spec" in doc, "")
        check(f"{name} がビルドコマンドを載せている",
              "pyinstaller packaging/shadow-clerk.spec" in doc, "")
        # uv sync は宣言外のものを消す。uv pip install した PyInstaller は
        # 次の uv sync --extra で消えるので、一時的な層に載せる
        # 本文では「やらないこと」として名前を出すので、コマンド行だけを見る
        cmds = [ln.strip() for ln in doc.splitlines()]
        check(f"{name} が --with で走らせている",
              "--with pyinstaller" in doc
              and "uv pip install pyinstaller" not in cmds, "")


def test_pywinpty_is_declared() -> None:
    toml = open(os.path.join(os.path.dirname(__file__), "..", "pyproject.toml"),
                encoding="utf-8").read()
    check("pywinpty が win32 の依存にある",
          "pywinpty" in toml and "sys_platform == 'win32'" in toml, "")


def main() -> int:
    test_no_posix_only_module_imports_at_top_level()
    test_imports_with_posix_modules_blocked()
    test_windows_pty_translates_to_bytes()
    test_windows_pty_lifecycle()
    test_backend_is_chosen_by_platform()
    test_missing_pywinpty_is_reported_not_raised()
    test_daemonize_does_not_fork_on_windows()
    test_spec_collects_the_packages_that_ship_data()
    test_readme_documents_the_build()
    test_pywinpty_is_declared()
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
