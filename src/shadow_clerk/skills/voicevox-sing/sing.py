#!/usr/bin/env python3
"""VOICEVOX エンジンで楽譜 JSON を歌わせて wav に書き出し、再生する。

使い方:
  python3 -I sing.py score.json out.wav [--play] [--engine URL] [--query-speaker 6000] [--speaker 3011]

score.json の形:
  {"notes": [["に", 60, 14], ["ち", 62, 14], [null, null, 20]]}
  各要素は [歌詞(ひらがな1モーラ), MIDIノート番号, フレーム数]。休符は歌詞も音も null。
  フレーム数は 1 フレーム ≒ 10.7ms（約 93.75 fps）。14 で約 0.15 秒。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.request


def post(url: str, body: object) -> bytes:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return urllib.request.urlopen(req, timeout=120).read()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("score")
    ap.add_argument("out")
    ap.add_argument("--play", action="store_true")
    ap.add_argument("--mp3-dir", default="songs", help="MP3 の保存先（空文字で保存しない）。既定は作業ディレクトリの songs/")
    ap.add_argument("--engine", default="http://localhost:50021")
    ap.add_argument("--query-speaker", type=int, default=6000)  # type=sing の歌唱教師
    ap.add_argument("--speaker", type=int, default=3011)  # type=frame_decode の声（既定: 玄野武宏）
    a = ap.parse_args()

    raw = json.load(open(a.score))["notes"]
    notes = [{"key": None, "frame_length": 20, "lyric": ""}]  # 先頭に休符が必須
    for lyric, key, frames in raw:
        notes.append({"key": key, "frame_length": frames, "lyric": lyric or ""})
    notes.append({"key": None, "frame_length": 20, "lyric": ""})

    q = json.loads(post(f"{a.engine}/sing_frame_audio_query?speaker={a.query_speaker}", {"notes": notes}))
    wav = post(f"{a.engine}/frame_synthesis?speaker={a.speaker}", q)
    open(a.out, "wb").write(wav)
    print(f"wrote {a.out} ({len(wav)} bytes)")
    if a.mp3_dir:  # 歌うたびに MP3 でも残す
        os.makedirs(a.mp3_dir, exist_ok=True)
        mp3 = os.path.join(a.mp3_dir, os.path.splitext(os.path.basename(a.out))[0] + ".mp3")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", a.out, "-codec:a", "libmp3lame", "-q:a", "2", mp3], check=True)
        print(f"wrote {mp3}")
    if a.play:
        subprocess.run(["aplay", "-q", a.out], check=False)


if __name__ == "__main__":
    main()
