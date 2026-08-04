# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## KNOTE（ノート）とは

社内向けの営業商談・ロープレ評価 Web アプリ。Talk（話す）＋ Knot（結び目・絆）。
動画/音声から声のトーン・間・発話比率を分析し、お客様の感情の動きを
タイムスタンプ付きで可視化する、**ポジティブな振り返り**ツール。住宅営業の文脈
（「理想の家」を提案する商談）を前提とする。UI もこのコンセプトに合わせた
オシャレでキャッチーなトーンを保つこと。

## コマンド

```bash
pip install -r requirements.txt          # 実行用の依存
pip install -r requirements-dev.txt      # 開発用（pytest を含む）
cp .env.example .env                      # 環境変数を用意（要編集）
streamlit run app.py                      # 起動（http://localhost:8501）

pytest                                    # テスト一式
pytest tests/test_models.py::test_total_and_score_for   # 単一テスト

python3 scripts/check_setup.py            # .env 点検＋Gemini接続テスト
python3 scripts/analyze_video.py talk.mp4 # Streamlit抜きで動画解析を試す
```

セットアップ詳細（GCP OAuth / Gemini キー）は `docs/SETUP.md`。
テストはネットワーク不要（Gemini/Drive はモック）。`pyproject.toml` で
`pythonpath=.` を設定済みのためリポジトリ直下から `pytest` を実行する。

## アーキテクチャ

レイヤーごとにディレクトリを分離している。データフローは
**ログイン → 動画選択（アップロード or Drive）→ Gemini 解析 → 評価結果表示**。

- `app.py` — 唯一の Streamlit エントリポイント。認証ゲートで未ログインなら
  ログイン画面、ログイン済みならタブ UI を出す。**Streamlit のネイティブ
  `pages/` マルチページは使わず**、`current_user()` による単一ゲート方式で
  ドメイン制限を一元化している。
- `config/settings.py` — **環境変数と評価項目(5項目)の唯一の真実**。
  `EVALUATION_CRITERIA` を UI・プロンプト・結果モデルすべてが参照する。
  項目を増減するときは必ずここを起点に変更する。ドメイン許可は
  `is_allowed_domain()`、管理者判定は `is_admin()`。
- `auth/google_oauth.py` — Google OAuth。`GOOGLE_OAUTH_SCOPES` で認可し、
  ドメイン検証後に `session_state['user']` と Drive 用 Credentials を保持する。
- `services/` — 外部連携。`google_drive.py`（Meet 録画の一覧/取得）、
  `gemini_analyzer.py`（google-genai での動画解析）、`storage.py`（模範トーク・
  評価履歴の永続化）。`auth` が持つ Credentials を受け取って動く。
- `core/` — ドメインロジック。`models.py`（`EvaluationResult` /
  `TimestampedFeedback` 等）、`prompts.py`（Gemini プロンプト組み立て）。
- `ui/` — `theme.py`（ブランドカラー・CSS）、`components.py`（ロゴ/ヒーロー/
  評価項目カード/サイドバー）。

### リリースの進め方（必ず守る）

プランナー8名が毎日使うので、**いきなり全員に出さない**。
まず先行公開の対象者（`settings.CANARY_EMAILS`、既定 `hkumada@`）で確かめ、
問題なければ全員に出す。**push＝全員公開**（Streamlit Cloud は main を見ている）。

- **画面に出る機能** … `config/settings.py` にフラグを既定OFFで足し、
  `settings.feature_visible(name, email)` で出し分ける。対象者と管理者だけに見える。
  確認後にフラグをONにして全員へ。
- **評価の中身**（プロンプト・称号・採点）… フラグで隠せないので、
  **push 前に対象者の実データ1件で動かして出力を目視**してから出す。
- **通知**（Chatリマインド）… `--dry-run` で対象と本文を確認し、
  対象者へ1通だけ実際に送ってから全員へ。

手順の詳細と判断基準は `docs/RELEASE_FLOW.md`。

### 重要な約束ごと

- **評価結果の構造を一致させる**: `core/prompts.py` が要求する JSON、
  `core/models.py` のデータクラス、UI の描画は同じフィールド名で揃える
  （`scores[].key` は `settings` の `Criterion.key`、`feedback` は
  timestamp + before/after のセット）。
- **アクセス制御は二段**: `ALLOWED_DOMAINS` でログイン可否、`ADMIN_EMAILS` で
  模範トーク登録などの管理操作可否。どちらも `.env` で変更する。
- **秘密情報**は `.env` / `.streamlit/secrets.toml` に置き、`data/` の実体
  （評価履歴・模範トーク動画）と共にコミットしない（`.gitignore` 済み）。

### 現状

①〜⑤すべて実装済み（Google OAuth / Drive / Gemini 解析 / 評価結果画面 /
模範トーク・履歴）。`GOOGLE_CLIENT_ID`・`GOOGLE_CLIENT_SECRET` が未設定の
場合のみ、`app.py` はデモログインにフォールバックする（Drive 連携は
本物の OAuth が必要なため利用不可）。動作には `.env` の
`GOOGLE_CLIENT_*` / `GEMINI_API_KEY` 設定が必要。

未実施: 自動テスト（pytest 未導入）。コア（`config.settings` の判定、
`core.models` の JSON ラウンドトリップ、`core.prompts`）は純 Python なので
テストを足しやすい。
