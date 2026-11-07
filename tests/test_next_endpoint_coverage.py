"""ダッシュボードの全 /api/* ルートが、新 UI が読み込む JS（_NEXT_JS・流用モジュール込み）に出てくるか、UI 外の許可リストにある

読み込んだ JS にパスが出てくるかを見るだけで、その画面から実際に呼ばれるかまでは見ない（流用モジュールの使わない関数も数える）

実行: uv run pytest -q tests/test_next_endpoint_coverage.py
"""
from __future__ import annotations

import inspect
import re

from shadow_clerk._daemon_dashboard_base import _DashboardHandlerBase
from shadow_clerk._daemon_dashboard_next_js import _NEXT_JS

# 画面を持たないルート（対応表の「UI 外」）。呼ぶ側と理由
OUT_OF_UI: dict[str, str] = {
    "/api/session": "clerk-meeting-helper / clerk-talk スキル",
    "/api/meeting-config/resolve": "clerk-meeting-helper スキル（公開・調査）",
    "/api/meeting-history": "clerk-practice スキル（前回までの練習）",
    "/api/watch": "スキルの transcript 監視（long poll）",
    "/api/generated": "スキルが作ったファイルの登録",
    "/api/speaking": "clerk-talk スキル（いま話しているか）",
    "/api/misheard": "clerk-talk スキル（聞き間違いの登録）",
    "/api/speaker-roster": "スキルが参照する話者一覧",
    "/api/pronounce": "clerk-practice スキル（発音の判定）",
    "/api/talk-end": "clerk-talk スキル（会議を終える）",
    "/api/talk-voice": "clerk-practice スキル（発音の練習で英語を標準の声にする）",
    "/api/language": "clerk-talk / clerk-practice スキル（認識言語の切り替え）",
    "/api/mute": "clerk-practice スキル（相手側の音を止める）",
    "/api/summary/notify": "要約を書いた側（スキル / clerk-util）からの通知",
    "/api/screenshot": "POST はブラウザ拡張（GET は本文中のリンクで新 UI からも使う）",
    # 対応表は「speech（そのまま移植）」に置いているが、現行 JS も fetch しない。スキルが話すための口で、
    # ダッシュボードは結果を SSE（talk_speak）で受けるだけ
    "/api/say": "clerk-talk / clerk-practice スキル（応答の読み上げ）",
}

# 新 UI では意図して使わない現行だけの経路（ある場合は理由を書く）
DEAD_IN_NEXT: dict[str, str] = {}


def _routes() -> set[str]:
    src = inspect.getsource(_DashboardHandlerBase.do_GET) + inspect.getsource(_DashboardHandlerBase.do_POST)
    return set(re.findall(r'path == "(/api/[^"]+)"', src))


def _called(route: str) -> bool:
    """JS の文字列リテラルの先頭にある（'/api/x' / '/api/x?'+q / `/api/x?${q}`）。コメント中の言及は数えない"""
    return re.search(r"""['"`]""" + re.escape(route) + r"""['"`?]""", _NEXT_JS) is not None


def test_every_api_route_is_called_or_listed() -> None:
    routes = _routes()
    assert len(routes) > 50
    unassigned = sorted(r for r in routes if not _called(r) and r not in OUT_OF_UI and r not in DEAD_IN_NEXT)
    print("unassigned:", unassigned)
    assert not unassigned, unassigned


def test_lists_are_not_stale() -> None:
    routes = _routes()
    assert not (set(OUT_OF_UI) | set(DEAD_IN_NEXT)) - routes
    # 新 UI が呼ぶようになったら許可リストから外す（/api/screenshot は GET を新 UI が使う）
    assert sorted(r for r in OUT_OF_UI if _called(r)) == ["/api/screenshot"]
    assert not [r for r in DEAD_IN_NEXT if _called(r)]
