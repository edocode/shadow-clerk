"""talk mode API の検証

実行: uv run python tests/test_talk_api.py
"""
from __future__ import annotations
import io
import json
import os
import sys
import tempfile

os.environ.setdefault(
    "SHADOW_CLERK_DATA_DIR", os.path.join(tempfile.gettempdir(), "shadow-clerk-talk-api-test"))
os.makedirs(os.environ["SHADOW_CLERK_DATA_DIR"], exist_ok=True)

from shadow_clerk._daemon_dashboard_ops_talk import _DashboardHandlerTalkOps as Ops  # noqa: E402
from shadow_clerk._daemon_talk import TalkStartError  # noqa: E402
from shadow_clerk._daemon_tts import TtsError  # noqa: E402
from shadow_clerk.domain import TalkVoice  # noqa: E402

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class _Talk:
    def __init__(self, reachable: bool = True) -> None:
        self.calls: list[tuple] = []
        self.reachable = reachable

    def voices(self) -> list[dict]:
        if not self.reachable:
            raise TtsError("down")
        return [{"id": 3, "name": "テスト（ノーマル）"}]

    def preview(self, voice: TalkVoice, text: str) -> None:
        if not self.reachable:
            raise TtsError("down")
        self.calls.append(("preview", voice, text))

    def start(self, topic: str, persona: str | None, workdir: str | None = None, route: str | None = None) -> None:
        if topic == "boom":
            raise TalkStartError("VOICEVOX down")
        self.calls.append(("start", topic, persona, workdir, route))

    def stop(self) -> None:
        self.calls.append(("stop",))

    def api_say(self, text: str) -> str | None:
        if text == "遮られた":
            return "途中の文。"
        self.calls.append(("say", text))
        return None

    def end_after_speech(self) -> bool:
        self.calls.append(("end",))
        return True

    def route_targets(self) -> dict:
        return {"available": True, "targets": [{"app": "Chromium", "label": "Chromium — WebRTC"}]}

    def speaking(self) -> list[str]:
        return ["monitor"] if self.reachable else []

    def snapshot(self) -> dict:
        return {"active": bool(self.calls)}


class _FakeHandler(Ops):
    def __init__(self, body: object = None, client: str = "127.0.0.1", reachable: bool = True) -> None:
        raw = json.dumps(body if body is not None else {}).encode("utf-8")
        self.client_address = (client, 12345)
        self.headers = {"Content-Length": str(len(raw))}
        self.rfile = io.BytesIO(raw)
        self.sent: dict = {}
        self.talk = _Talk(reachable)
        self.recorder = type("_Rec", (), {"talk": self.talk})()

    def _send_json(self, data: dict) -> None:
        self.sent = data


def test_start_stop() -> None:
    h = _FakeHandler({"on": True, "topic": "設計", "persona": "devil"})
    h._set_talk_mode()
    check("開始", h.talk.calls == [("start", "設計", "devil", None, None)] and h.sent["status"] == "ok", repr(h.sent))
    h = _FakeHandler({"on": True})
    h._set_talk_mode()
    check("persona 省略は None", h.talk.calls == [("start", "", None, None, None)], repr(h.talk.calls))
    h = _FakeHandler({"on": True, "workdir": "~/work"})
    h._set_talk_mode()
    check("作業ディレクトリを渡す", h.talk.calls == [("start", "", None, "~/work", None)], repr(h.talk.calls))
    h = _FakeHandler({"on": True, "workdir": 3})
    h._set_talk_mode()
    check("文字列でない作業ディレクトリは拒否", h.sent.get("status") == "error" and h.talk.calls == [])
    h = _FakeHandler({"on": False})
    h._set_talk_mode()
    check("停止", h.talk.calls == [("stop",)])


def test_start_error() -> None:
    h = _FakeHandler({"on": True, "topic": "boom"})
    h._set_talk_mode()
    check("開始失敗はメッセージを返す", h.sent == {"status": "error", "message": "VOICEVOX down"}, repr(h.sent))


def test_validation() -> None:
    for body, label in [({"on": "yes"}, "on が bool でない"), ({"on": True, "topic": 1}, "topic が文字列でない"),
                        ({"on": True, "topic": "x" * 501}, "topic が長すぎる"),
                        ({"on": True, "persona": 3}, "persona が文字列でない")]:
        h = _FakeHandler(body)
        h._set_talk_mode()
        check(f"{label}は拒否", h.sent.get("status") == "error" and h.talk.calls == [], repr(h.sent))
    for body, label in [({"text": ""}, "空の text"), ({"text": "x" * 2001}, "長すぎる text"), ({"text": 1}, "数値の text")]:
        h = _FakeHandler(body)
        h._say()
        check(f"{label}は拒否", h.sent.get("status") == "error" and h.talk.calls == [], repr(h.sent))


def test_say_and_remote() -> None:
    h = _FakeHandler({"text": "遮られた"})
    h._say()
    check("制止の直後は interrupted と止めた文", h.sent == {"status": "interrupted", "cut": "途中の文。"}
          and h.talk.calls == [], repr(h.sent))
    h = _FakeHandler({"text": "テストです"})
    h._say()
    check("say を渡す", h.talk.calls == [("say", "テストです")] and h.sent["status"] == "ok")
    h = _FakeHandler({"text": "x"}, client="10.0.0.9")
    h._say()
    check("外部からは拒否", h.sent.get("status") == "error" and h.talk.calls == [])
    h = _FakeHandler(client="10.0.0.9")
    h._serve_talk_mode()
    check("GET も外部からは拒否", h.sent.get("status") == "error")


def test_talk_end() -> None:
    h = _FakeHandler()
    h._end_talk()
    check("読み上げ後の終了を頼む", h.talk.calls == [("end",)] and h.sent == {"status": "ok", "ending": True}, repr(h.sent))
    h = _FakeHandler(client="10.0.0.9")
    h._end_talk()
    check("外部からの終了は拒否", h.sent.get("status") == "error" and h.talk.calls == [])


def test_voices() -> None:
    h = _FakeHandler()
    h._serve_talk_voices()
    check("話者一覧を返す", h.sent == {"status": "ok", "voices": [{"id": 3, "name": "テスト（ノーマル）"}]}, repr(h.sent))
    h = _FakeHandler(reachable=False)
    h._serve_talk_voices()
    check("エンジン不達はエラー", h.sent == {"status": "error", "message": "down"}, repr(h.sent))
    h = _FakeHandler(client="10.0.0.9")
    h._serve_talk_voices()
    check("話者一覧も外部からは拒否", h.sent.get("status") == "error" and "message" in h.sent)


def test_preview() -> None:
    h = _FakeHandler({"text": "試し", "voice": {"speaker_id": 8, "speed": 1.2}})
    h._talk_preview()
    check("試聴に声と文を渡す", h.talk.calls == [("preview", TalkVoice(speaker_id=8, speed=1.2), "試し")]
          and h.sent["status"] == "ok", repr(h.talk.calls))
    h = _FakeHandler({})
    h._talk_preview()
    check("文を省略すると既定の試聴文", len(h.talk.calls) == 1 and h.talk.calls[0][2], repr(h.talk.calls))
    for body, label in [({"voice": {"speed": 9}}, "範囲外の話速"), ({"voice": "fast"}, "dict でない voice"),
                        ({"text": 1}, "数値の text")]:
        h = _FakeHandler(body)
        h._talk_preview()
        check(f"試聴で{label}は拒否", h.sent.get("status") == "error" and h.talk.calls == [], repr(h.sent))
    h = _FakeHandler({}, reachable=False)
    h._talk_preview()
    check("試聴でエンジン不達はエラー", h.sent == {"status": "error", "message": "down"}, repr(h.sent))


def test_route() -> None:
    h = _FakeHandler()
    h._serve_talk_route_targets()
    check("届ける先の候補を返す", h.sent == {"available": True, "targets": [{"app": "Chromium", "label": "Chromium — WebRTC"}]},
          repr(h.sent))
    h = _FakeHandler(client="10.0.0.9")
    h._serve_talk_route_targets()
    check("候補も外部からは拒否", h.sent.get("status") == "error")
    h = _FakeHandler({"on": True, "route": "Chromium"})
    h._set_talk_mode()
    check("届ける先を渡す", h.talk.calls == [("start", "", None, None, "Chromium")], repr(h.talk.calls))
    h = _FakeHandler({"on": True, "route": ""})
    h._set_talk_mode()
    check("空文字は届ける先なし", h.talk.calls == [("start", "", None, None, None)], repr(h.talk.calls))
    for body, label in [({"on": True, "route": 3}, "文字列でない"), ({"on": True, "route": "x" * 201}, "長すぎる")]:
        h = _FakeHandler(body)
        h._set_talk_mode()
        check(f"{label}届ける先は拒否", h.sent.get("status") == "error" and h.talk.calls == [], repr(h.sent))


def test_speaking() -> None:
    h = _FakeHandler()
    h._serve_speaking()
    check("話していれば speaking が真", h.sent == {"speaking": True, "sources": ["monitor"]}, repr(h.sent))
    h = _FakeHandler(reachable=False)
    h._serve_speaking()
    check("誰も話していなければ偽", h.sent == {"speaking": False, "sources": []}, repr(h.sent))
    h = _FakeHandler(client="10.0.0.9")
    h._serve_speaking()
    check("外部からは拒否", h.sent.get("status") == "error")


if __name__ == "__main__":
    test_voices()
    test_preview()
    test_start_stop()
    test_start_error()
    test_validation()
    test_speaking()
    test_say_and_remote()
    test_talk_end()
    test_route()
    sys.exit(0 if all(results) else 1)
