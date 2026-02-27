# 目的

Ubuntu環境で、Web会議の音声を録音・ローカルで文字起こししてテキストファイルに継続的に書き出すシステムと、それをClaude CodeからSkill（またはカスタムコマンド）として呼び出して翻訳・要約する連携システムを作成してください。

# 全体アーキテクチャ

【モジュールA：ローカル録音・文字起こしデーモン】
- Ubuntuのシステム音声（相手）とマイク（自分）をミックスして録音。
- 発話の区切りごとに細かくチャンク化（またはストリーミング処理）し、ローカルの `faster-whisper` で文字起こしを実行。
- 結果を `transcript.txt` にタイムスタンプ付きでリアルタイムに追記（Append）し続ける。

【モジュールB：Claude Code連携（翻訳・要約Skill）】
- Claude Codeが `transcript.txt` を読み込み、要約・翻訳を行って `summary.md` に出力・更新するための仕組み（MCPサーバー、またはClaude Codeから呼び出せるラッパースクリプト）を構築する。

# Claude Codeへの実装指示

以下のステップで開発と環境構築のサポートをお願いします。

## 1. モジュールA（録音と文字起こし）の作成

- `pyaudio` や `sounddevice` などを使い、PulseAudio/PipeWire環境でマイクとシステム音声（monitorデバイス）を同時キャプチャするPythonスクリプト `recorder.py` を作成してください。
- リアルタイム性を高めるため、VAD（Voice Activity Detection）等を用いて無音区間で音声を区切り、`faster-whisper` (モデル: small) に渡してテキスト化するロジックを実装してください。
- 認識したテキストは順次 `transcript.txt` に書き出してください。

## 2. モジュールB（Claude Code連携）の作成

- Claude Codeから手軽に「現在の `transcript.txt` を読んで、日本語の議事録として `summary.md` に出力して」と指示できるような最適なアプローチ（特定のSkillの実装、またはプロンプトテンプレートの作成）を提案・実装してください。
- 必要であれば、差分だけを読み込んで `summary.md` を逐次更新していくようなスクリプトを書いて、Claude Codeにそれを実行させる形でも構いません。

## 3. 必要なパッケージのインストール

- `ffmpeg`, `faster-whisper`, `webrtcvad` (必要な場合) などのインストールコマンドを提示・実行してください。
- README.md にSetupの手順として記載する。
