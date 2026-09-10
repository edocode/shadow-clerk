"""webrtcvad の配布名を教えるフック

PyInstaller 同梱の contrib フックは `copy_metadata('webrtcvad')` を呼ぶが、
このプロジェクトが使うのは **webrtcvad-wheels**(import 名だけが webrtcvad)。
配布メタデータが見つからず、ビルドが `ImportErrorWhenRunningHook` で止まる。

同じモジュール名のフックは 1 つしか採用されず、`hookspath` に置いたものが
同梱フックより優先されるので、ここで正しい配布名を渡して差し替える。
"""
from PyInstaller.utils.hooks import copy_metadata

try:
    datas = copy_metadata("webrtcvad-wheels")
except Exception:                                  # noqa: BLE001
    # 素の webrtcvad が入っている環境もありうる。メタデータは無くても動く
    datas = []
