"""TalKnot のアプリ設定（環境変数・定数・評価項目の定義）。

評価項目（5項目）はこのモジュールを唯一の真実とする。
UI 表示・Gemini プロンプト・評価結果モデルはすべてここを参照すること。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- パス ---
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
REFERENCE_TALKS_DIR = DATA_DIR / "reference_talks"   # 管理者が登録する模範トーク
EVALUATIONS_DIR = DATA_DIR / "evaluations"           # 評価結果の履歴

# --- 永続化（Cloud Storage）---
# 設定すると模範トーク・評価履歴を GCS バケットに保存する（Cloud Run 等で永続化）。
# 未設定ならローカルファイル（DATA_DIR）を使う（ローカル開発・テスト用）。
GCS_BUCKET = os.getenv("GCS_BUCKET", "")
# バケット内のプレフィックス（フォルダ）。
GCS_PREFIX = os.getenv("GCS_PREFIX", "talknot")


def _csv_env(key: str, default: str = "") -> list[str]:
    return [v.strip() for v in os.getenv(key, default).split(",") if v.strip()]


# --- アクセス制御 ---
# ログインを許可する組織ドメイン。本番では .env で自社ドメインに変更する。
ALLOWED_DOMAINS = _csv_env("ALLOWED_DOMAINS", "yourcompany.com")
# 模範トーク登録などの管理者操作を許可するメール。
ADMIN_EMAILS = _csv_env("ADMIN_EMAILS")

# --- Google OAuth / Drive ---
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:8501")
# Drive は読み取りのみ。userinfo はドメイン判定に使用。
GOOGLE_OAUTH_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/drive.readonly",
]

# --- サービスアカウント / ドメイン全体委任（DWD）---
# 8アカウントのドライブを代理アクセスするためのサービスアカウント鍵(JSON)のパス。
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
# 評価対象として代理アクセスするメンバー（カンマ区切り）。
TARGET_ACCOUNTS = _csv_env(
    "TARGET_ACCOUNTS",
    ",".join(
        [
            "s.kageyama@life-time-support.com",
            "hkumada@life-time-support.com",
            "kkyoya@life-time-support.com",
            "yhoshino@life-time-support.com",
            "ynakatani@life-time-support.com",
            "amoritani@life-time-support.com",
            "toshima@life-time-support.com",
            "manguri@life-time-support.com",
        ]
    ),
)
# 模範トークの基準とするアカウント（カンマ区切りで複数可）。
REFERENCE_ACCOUNTS = _csv_env(
    "REFERENCE_ACCOUNTS",
    ",".join(
        [
            "kkyoya@life-time-support.com",
            "hkumada@life-time-support.com",
        ]
    ),
)
# 旧来の単数参照との後方互換（先頭を既定の基準アカウントとする）。
REFERENCE_ACCOUNT = os.getenv(
    "REFERENCE_ACCOUNT",
    REFERENCE_ACCOUNTS[0] if REFERENCE_ACCOUNTS else "kkyoya@life-time-support.com",
)
# サービスアカウントに委任する Drive スコープ（読み取り専用）。
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# --- 弊社ナレッジの永続保存（共有ドライブのスプレッドシート）---
# 専用AIの頭脳（社内ルール・商品知識・営業トーク）を、再起動でも消えないよう
# Google スプレッドシートに保存する。未設定ならローカルファイル（DATA_DIR）に保存。
#   KNOWLEDGE_SHEET_ID … 共有ドライブに置いたスプレッドシートの ID
#   KNOWLEDGE_SA_JSON  … 書き込み用サービスアカウント鍵の JSON 文字列（Secrets 向け）
#   KNOWLEDGE_SA_FILE  … 同 鍵ファイルのパス（ローカル開発向け）
# 鍵は「このシート1枚だけ」共有した最小権限の専用アカウントを推奨（録画用の鍵は使わない）。
KNOWLEDGE_SHEET_ID = os.getenv("KNOWLEDGE_SHEET_ID", "")
KNOWLEDGE_SA_JSON = os.getenv("KNOWLEDGE_SA_JSON", "")
KNOWLEDGE_SA_FILE = os.getenv("KNOWLEDGE_SA_FILE", "")
KNOWLEDGE_SHEET_TAB = os.getenv("KNOWLEDGE_SHEET_TAB", "Knowledge")
SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# --- Gemini ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# 動画・音声解析に対応したモデル。.env で差し替え可能。
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def is_admin(email: str | None) -> bool:
    return bool(email) and email in ADMIN_EMAILS


def is_allowed_domain(email: str | None) -> bool:
    if not email or "@" not in email:
        return False
    return email.split("@", 1)[1].lower() in {d.lower() for d in ALLOWED_DOMAINS}


# --- 評価項目（1〜5段階）---
@dataclass(frozen=True)
class Criterion:
    key: str          # 内部キー / Gemini 出力のフィールド名
    number: str       # 表示用の番号（①〜⑤）
    title: str        # 短いタイトル
    description: str   # 何を見るか
    icon: str         # UI 用アイコン


EVALUATION_CRITERIA: list[Criterion] = [
    Criterion(
        key="additional_consideration",
        number="①",
        title="追加検討が増えたか",
        description="商談を通じてお客様の検討項目・興味が広がり、次の一歩につながったか。",
        icon="🌱",
    ),
    Criterion(
        key="adaptability",
        number="②",
        title="臨機応変に対応ができるか",
        description="お客様の反応や想定外の質問に対し、柔軟に切り返し対応できていたか。",
        icon="🤸",
    ),
    Criterion(
        key="emotion_catch",
        number="③",
        title="お客様の感情をキャッチできているか",
        description="声のトーン・間・表情から感情の動きを読み取り、適切に拾えていたか。",
        icon="💗",
    ),
    Criterion(
        key="background_depth",
        number="④",
        title="お客様の背景を深掘れたか",
        description="秘密領域（実家との距離・子供・引越し時期と年齢など）まで信頼関係を築いて踏み込めたか。",
        icon="🔍",
    ),
    Criterion(
        key="excitement",
        number="⑤",
        title="雰囲気よくワクワクしたか",
        description="「任せたら理想の家ができる」という期待値が高まり、会話が弾んでいたか。",
        icon="✨",
    ),
]

CRITERIA_BY_KEY = {c.key: c for c in EVALUATION_CRITERIA}


# --- 評価の2軸（各項目をこの2視点で採点する）---
@dataclass(frozen=True)
class Axis:
    key: str          # Gemini 出力のフィールド接頭辞（reference_score / sales_score）
    title: str        # 表示名
    description: str   # 何の視点か
    icon: str         # UI 用アイコン


EVALUATION_AXES: list[Axis] = [
    Axis(
        key="reference",
        title="模範トーク視点",
        description="登録された模範トーク（無ければ住宅営業トップの理想トーク）と比べて、どれだけ近づけたか。",
        icon="🎯",
    ),
    Axis(
        key="sales",
        title="営業プロ視点",
        description="住宅営業のトップセールス兼コーチとして見た、その項目の完成度。",
        icon="💼",
    ),
]
AXES_BY_KEY = {a.key: a for a in EVALUATION_AXES}

# --- 営業特化AIペルソナ（評価者の人格）---
# 評価プロンプトの冒頭に置き、AIに「住宅営業のプロ」として振る舞わせる。
SALES_AI_PERSONA = (
    "あなたは住宅営業のトップセールスであり、後輩を本気で伸ばすロープレコーチです。"
    "「理想の家」を一緒に描く商談を数百件成約させてきた実績があり、"
    "お客様の本音・不安・ワクワクを、声のトーン・間・発話比率から敏感に読み取ります。"
    "評価は常にポジティブで、できている点を具体的に称えたうえで、"
    "次にどう言えばさらに刺さるかを営業現場の言葉で示します。"
)
