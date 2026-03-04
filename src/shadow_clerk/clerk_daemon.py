#!/usr/bin/env python3
"""Shadow-clerk daemon: 音声キャプチャ・VAD・文字起こし

このファイルは後方互換シムです。実装は以下のモジュールに分割されています:
  _daemon_constants.py  - 定数・デフォルト設定
  _daemon_config.py     - 設定管理
  _daemon_audio.py      - 音声バックエンド
  _daemon_vad.py        - VAD セグメンテーション
  _daemon_transcriber.py - 用語置換・文字起こし
  _daemon_recorder.py   - メインレコーダー
  _daemon_dashboard.py  - Web ダッシュボード
  _daemon_main.py       - エントリーポイント
"""

from shadow_clerk._daemon_constants import *  # noqa: F401, F403
from shadow_clerk._daemon_config import *  # noqa: F401, F403
from shadow_clerk._daemon_audio import *  # noqa: F401, F403
from shadow_clerk._daemon_vad import *  # noqa: F401, F403
from shadow_clerk._daemon_transcriber import *  # noqa: F401, F403
from shadow_clerk._daemon_dashboard import *  # noqa: F401, F403
from shadow_clerk._daemon_recorder import *  # noqa: F401, F403
from shadow_clerk._daemon_main import main  # noqa: F401

if __name__ == "__main__":
    main()
