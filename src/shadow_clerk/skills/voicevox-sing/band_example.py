"""voicevox-sing のバンド伴奏の実例。使い方: python band_example.py <sing.py のパス>"""
from __future__ import annotations

import json, subprocess, wave, sys
import numpy as np
import tinysoundfont as tsf

SR = 44100
FPS = 24000 / 256            # 歌のフレーム数/秒
Q = 48                       # 4分音符 = 48 フレーム
BAR = Q * 4
S = "."                      # 作業ディレクトリ

def ph(lyr: str, keys: list[int], durs: list[int]) -> list[tuple[str, int, int]]:
    return list(zip(list(lyr), keys, durs))

def stac(notes: list[tuple[str, int, int]]) -> list[list]:
    out = []
    for l, k, d in notes:
        out += [[l, k, d - 4], [None, None, 4]] if d <= 20 else [[l, k, d]]
    return out

up = 12
A  = ph("ごろごろごろねなのだ", [60,62,64,67,64,62,60,64,67,64], [12]*9 + [36])
B  = ph("にちようびのごろね", [62,64,67,69,67,64,62,64], [12,12,12,12,24,12,12,36])
H  = ph("げつようびよまだくるな", [72,72,71,69,67,69,72,74,72,69,67], [12,12,12,12,24,12,12,12,12,12,48])
H2 = ph("げつようびよまだくるな", [72,72,71,69,67,69,74,76,74,72,67], [12,12,12,12,24,12,12,12,12,12,60])
E  = ph("ごろごろごろねなのだ", [60,62,64,67,64,62,60,64,67,60], [12]*9 + [100])
parts = [A, B, H, H2, A, B, H, H2, E]
chords = ["C", "Am", "F", "G", "C", "Am", "F", "G", "C"]

notes = [[None, None, BAR]]  # 頭に 1 小節のドラムだけのイントロ
for p in parts:
    total = sum(d for _, _, d in p)
    pad = (-total) % BAR
    notes += stac([(l, k + up, d) for l, k, d in p])
    if pad:
        notes += [[None, None, pad]]
json.dump({"notes": notes}, open("band.json", "w", encoding="utf-8"), ensure_ascii=False)
subprocess.run(["python3", "-I", sys.argv[1], "band.json", "vocal.wav", "--speaker", "3003", "--mp3-dir", ""], check=True)

# ---- 伴奏（GM 音源）----
bars = 1 + len(parts)         # イントロ + 本編。最後の小節は歌が伸びるので +1 余韻
t0 = 20 / FPS
bar_sec = BAR / FPS
CH = {"C": ([36, 36], [48,52,55,60]), "Am": ([33, 33], [45,52,57,60]),
      "F": ([29, 29], [41,48,53,57]), "G": ([31, 31], [43,50,55,59])}
ev = []  # (秒, on/off, ch, key, vel)
def note(t: float, dur: float, ch: int, key: int, vel: int) -> None:
    ev.append((t, 1, ch, key, vel)); ev.append((t + dur, 0, ch, key, 0))
eighth = bar_sec / 8
for b in range(bars + 1):
    tb = t0 + b * bar_sec
    last = b == bars
    for i in range(8):
        te = tb + i * eighth
        if not last:
            note(te, eighth * 0.8, 9, 42, 70 if i % 2 else 95)               # ハイハット
        if i in (0, 5) or (i == 4 and b % 2): note(te, eighth, 9, 36, 115)  # キック
        if i in (2, 6): note(te, eighth, 9, 38, 105)                         # スネア
    if last:
        note(tb, bar_sec, 9, 49, 100); note(tb, bar_sec, 9, 36, 115)         # 最後はクラッシュ
    if b >= 1:
        name = chords[min(b - 1, len(chords) - 1)] if not last else "C"
        bass, gtr = CH[name]
        for i, (off, dur) in enumerate([(0, 1.5), (3, 1), (4, 1.5), (7, 1)]):    # ベース
            note(tb + off * eighth, dur * eighth * 0.9, 0, bass[0] + (12 if i == 3 else 0), 100)
        for off in ([0] if last else [2, 6]):                                 # ギター（裏のカッティング）
            for k in gtr:
                note(tb + off * eighth, eighth * (7 if last else 0.9), 1, k, 78)
        if b >= 3 and not last:                                                # サビからピアノで厚みを足す
            for k in gtr[1:]:
                note(tb, bar_sec * 0.9, 2, k + 12, 55)

ev.sort(key=lambda e: (e[0], e[1]))
syn = tsf.Synth(samplerate=SR)
sf = syn.sfload("/usr/share/sounds/sf2/TimGM6mb.sf2")
syn.program_select(0, sf, 0, 33)   # フィンガーベース
syn.program_select(1, sf, 0, 28)   # ミュートでない clean ギター（Electric Guitar clean）
syn.program_select(2, sf, 0, 4)    # エレピ
syn.program_select(9, sf, 0, 0, is_drums=True)
total = int((t0 + (bars + 1) * bar_sec + 3) * SR)
buf = []
pos = 0
for t, kind, ch, key, vel in ev:
    n = int(t * SR) - pos
    if n > 0:
        buf.append(np.frombuffer(bytes(syn.generate(n)), dtype=np.float32)); pos += n
    (syn.noteon(ch, key, vel) if kind else syn.noteoff(ch, key))
buf.append(np.frombuffer(bytes(syn.generate(max(total - pos, 0))), dtype=np.float32))
audio = np.concatenate(buf).reshape(-1, 2)
audio = np.clip(audio, -1, 1)
pcm = (audio * 32767).astype("<i2")
with wave.open("back.wav", "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
print("backing", len(audio) / SR, "sec")
