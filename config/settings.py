"""KNOTE のアプリ設定（環境変数・定数・評価項目の定義）。

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


def _bool_env(key: str, default: bool = False) -> bool:
    """環境変数を bool として読む（"1/true/yes/on" を True とみなす）。"""
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


# --- アクセス制御 ---
# ログインを許可する組織ドメイン。本番では .env で自社ドメインに変更する。
ALLOWED_DOMAINS = _csv_env("ALLOWED_DOMAINS", "yourcompany.com")
# 模範トーク登録などの管理者操作を許可するメール。
ADMIN_EMAILS = _csv_env("ADMIN_EMAILS")

# 閲覧専用：全メンバーの実績・成長を閲覧できるが、テンプレの編集・追加・削除など
# 書き込み操作は一切できない。既定に3名を入れておく（.env の VIEWER_EMAILS で変更可）。
VIEWER_EMAILS = _csv_env(
    "VIEWER_EMAILS",
    ",".join(
        [
            "ryouchiku@life-time-support.com",
            "rsuga@life-time-support.com",
            "k.sasaki@life-time-support.com",
        ]
    ),
)

# 評価がエラーになったとき、Google Chat の個人DMで通知する宛先（空なら通知しない）。
# 送信には Chat の設定（CHAT_SA_JSON 等）がアプリ側にも必要。未設定なら静かにスキップ。
ERROR_NOTIFY_EMAIL = os.getenv("ERROR_NOTIFY_EMAIL", "hkumada@life-time-support.com")

# --- 同時実行の制御（無料枠のメモリ保護）---
# 同時に走らせる動画解析の最大数。無料枠（RAM 約1GB）では 1 が安全。
# 余裕のあるホストに移したら増やせる（環境変数 MAX_CONCURRENT_ANALYSES）。
def _int_env(key: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(key, str(default))))
    except (TypeError, ValueError):
        return default


MAX_CONCURRENT_ANALYSES = _int_env("MAX_CONCURRENT_ANALYSES", 1)

# --- 初回商談の自動評価バッチ（scripts/auto_evaluate_meetings.py）---
# 1日あたりに自動評価する件数の上限（全プランナー合算・古い未処理から順に処理）。
# 無料枠・メモリ保護のため既定は控えめ。超過分は翌日以降に自然と持ち越す。
AUTO_EVAL_DAILY_LIMIT = _int_env("AUTO_EVAL_DAILY_LIMIT", 5)
# カレンダーを何日さかのぼって初回商談を探すか（録画が出揃うまでの猶予）。
AUTO_EVAL_LOOKBACK_DAYS = _int_env("AUTO_EVAL_LOOKBACK_DAYS", 14)
# この日付(YYYY-MM-DD)より前の商談は自動評価しない（稼働開始前の過去分を一括評価しないため）。
# 既定は稼働開始日。空にすると制限なし（さかのぼり分も対象）。
AUTO_EVAL_START_DATE = os.getenv("AUTO_EVAL_START_DATE", "2026-08-02")

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
    # 商談予定（Meet）をカレンダーから選ぶために追加。※追加後は一度だけ再ログインが必要。
    "https://www.googleapis.com/auth/calendar.readonly",
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
# 整備済みナレッジ資料（商品・料金・サービス・FAQ）が入った Drive フォルダ。
# 管理者がここから「社内ナレッジ資料」を取り込み・更新できる。
KNOWLEDGE_FOLDER_ID = os.getenv(
    "KNOWLEDGE_FOLDER_ID", "15Q4Ei08Xubfib_0T2HcwYpdk93BDudl8"
)
# 商談議事録フォルダ。新規議事録から実践ナレッジを増分抽出する対象。
# クラウドのボタンで読むには、このフォルダを知識SAに「閲覧者」で共有しておく。
MINUTES_FOLDER_ID = os.getenv("MINUTES_FOLDER_ID", "14yefycrO6ylPVT0LAqbh10HjrDV-9FDd")
# 議事録抽出に使うモデル（無料枠の広いものを推奨）。
MINUTES_EXTRACT_MODEL = os.getenv("MINUTES_EXTRACT_MODEL", "gemini-2.5-flash-lite")

# --- 施工事例ギャラリー（フックツール）---
# 施工事例の写真を保存する共有 Drive フォルダ。知識SAに「編集者」で共有しておく。
# アップロードは管理者のみ、閲覧・ダウンロードは全ユーザー可。
GALLERY_FOLDER_ID = os.getenv("GALLERY_FOLDER_ID", "")
# 施工事例のカテゴリ（アップロード時に選ぶ）。
GALLERY_CATEGORIES = _csv_env(
    "GALLERY_CATEGORIES",
    "コーティング,エコカラット,ダウンライト,オーダー家具,窓フィルム,その他",
)

# --- LTS共通「利用ログ」への記録 ---
# 誰が・どのツールを・いつ使ったかを共通シートに集約する。
USAGE_LOG_SHEET_ID = os.getenv(
    "USAGE_LOG_SHEET_ID", "17et2dnkgLsxpb9cdbKgDRmmkI5hB_LYyMYtqxZhIhUU"
)
USAGE_LOG_TAB = os.getenv("USAGE_LOG_TAB", "利用ログ")
# ツール台帳の左端IDと一致させる（未登録なら台帳に1行足して決める）。
USAGE_LOG_TOOL_ID = os.getenv("USAGE_LOG_TOOL_ID", "talknot")
SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
# 評価履歴の永続化先シート。未設定なら KNOWLEDGE_SHEET_ID と同じシート（Evaluations タブ）。
# 将来「評価専用の別シート」に分けたくなったら、ここに別シートIDを設定するだけ。
EVALUATIONS_SHEET_ID = os.getenv("EVALUATIONS_SHEET_ID", "")

# --- Gemini ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# 動画・音声解析に対応したモデル。.env で差し替え可能。
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
# 動画のフレーム抽出レート（fps）。低くするほどトークン消費が減り、長尺（2〜3時間）でも
# 文脈上限に収まりやすくなる。身振り手振りは 0.5fps 程度で十分読み取れる。
GEMINI_VIDEO_FPS = float(os.getenv("GEMINI_VIDEO_FPS", "0.5"))


def is_admin(email: str | None) -> bool:
    return bool(email) and email in ADMIN_EMAILS


def is_viewer(email: str | None) -> bool:
    """閲覧専用アカウントか。実績・成長の閲覧のみ可で、編集権限は持たない。"""
    return bool(email) and email in VIEWER_EMAILS


def can_view_all(email: str | None) -> bool:
    """全メンバーの実績・成長を閲覧してよいか（管理者＝編集も可 / 閲覧専用＝閲覧のみ）。"""
    return is_admin(email) or is_viewer(email)


def is_allowed_domain(email: str | None) -> bool:
    if not email or "@" not in email:
        return False
    return email.split("@", 1)[1].lower() in {d.lower() for d in ALLOWED_DOMAINS}


# --- 機能フラグ（feature flag）---
# 基礎習得までプランナーに見せたくない応用機能を、既定OFFで仕込むための仕組み。
# フラグOFF＆非管理者には出さず、管理者はOFFでもプレビューできる（feature_visible）。
# 応用①「反論・切り返しドリル」。基礎（導入・重点3商材）が身につくまで非表示にする。
FEATURE_OBJECTION_DRILL = _bool_env("FEATURE_OBJECTION_DRILL", True)

# 機能名 → フラグ値の対応表（未知の名前は False）。
_FEATURE_FLAGS = {
    "objection_drill": FEATURE_OBJECTION_DRILL,
}


# --- 先行公開（カナリア）---
# 新機能・修正は、まずこの人にだけ見せて確認し、問題なければ全員に出す。
# 管理者は「操作権限」、カナリアは「先行して新機能が見える人」で役割が別。
# .env の CANARY_EMAILS で差し替えられる（カンマ区切り・複数可）。
CANARY_EMAILS = _csv_env("CANARY_EMAILS", "hkumada@life-time-support.com")


def is_canary(email: str | None) -> bool:
    """先行公開の対象者か（新機能をフラグOFFのまま見られる人）。"""
    if not email:
        return False
    return email.lower() in {e.lower() for e in CANARY_EMAILS}


def feature_enabled(name: str) -> bool:
    """機能フラグが有効か＝全員に公開済みか（未知の名前は False）。"""
    return bool(_FEATURE_FLAGS.get(name, False))


def feature_visible(name: str, email: str | None) -> bool:
    """その機能をこのユーザーに見せてよいか。

    公開の段階：
      1. フラグOFF … 先行公開の対象者（CANARY_EMAILS）だけに見える＝ここで検証
      2. フラグON  … 全員に見える

    管理者にも見せるのは、確認を頼めるようにするため。プランナーには出ない。
    """
    return feature_enabled(name) or is_canary(email) or is_admin(email)


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
        title="臨機応変に対応できたか",
        description="お客様の反応や想定外の質問に対し、柔軟に切り返し対応できていたか。",
        icon="🤸",
    ),
    Criterion(
        key="emotion_catch",
        number="③",
        title="お客様の感情をつかめたか",
        description="声のトーン・間・表情から感情の動きを読み取り、適切に拾えていたか。",
        icon="💗",
    ),
    Criterion(
        key="background_depth",
        number="④",
        title="お客様の背景を深掘りできたか",
        description="秘密領域（実家との距離・子供・引越し時期と年齢など）まで信頼関係を築いて踏み込めたか。",
        icon="🔍",
    ),
    Criterion(
        key="excitement",
        number="⑤",
        title="ワクワクを引き出せたか",
        description="「任せたら理想の家ができる」という期待値が高まり、会話が弾んでいたか。",
        icon="✨",
    ),
]

CRITERIA_BY_KEY = {c.key: c for c in EVALUATION_CRITERIA}

# 1回の評価で出す隠れたニーズの上限。**0 以下なら制限しない（既定）**。
# 件数を絞ると、モデルが商談の前半だけを見て打ち切ってしまい、全体の
# フィードバックにならなかった。商談は最後まで読み取らせ、根拠のある指摘は
# すべて出す方針。異常に多いときだけ、この値を設定して抑える。
# _int_env は最低1を強制するので、ここでは 0（＝制限なし）を表せる素の読み方を使う。
def _limit_env(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


MAX_HIDDEN_NEEDS = _limit_env("MAX_HIDDEN_NEEDS", 0)


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
        description="登録した模範トークの“型・流れ・技術”をどれだけ再現できたか（再現度）。"
        "未登録なら住宅営業の基本の型に沿えたか。",
        icon="🎯",
    ),
    Axis(
        key="sales",
        title="営業プロ視点",
        description="模範に関係なく、お客様目線で見たトークそのものの本質的な質・完成度。",
        icon="💼",
    ),
]
AXES_BY_KEY = {a.key: a for a in EVALUATION_AXES}

# --- 業界用語集（新築マンションのインテリアオプション）---
# 音声認識は業界用語を同音の一般語に誤変換する（例「入隅」→「入り墨」）。
# 正しい用語をプロンプトに渡して寄せさせ、実際に出た誤りは後処理でも直す。
# 用語が増えたらここに足す（プロンプト・後処理の両方に自動で効く）。
INDUSTRY_GLOSSARY: dict[str, list[str]] = {
    "部位・納まり": [
        "入隅（いりすみ）", "出隅（ですみ）", "角（かど）", "巾木", "廻り縁",
        "見切り材", "下がり壁", "玄関框", "建具", "下地", "目地", "養生",
        "専有部", "共用部",
    ],
    "商材": [
        "エコカラット", "フロアコーティング", "UVコーティング", "ガラスコーティング",
        "シリコンコーティング", "ダウンライト", "人感センサー", "オーダー家具",
        "カップボード", "ピクチャーレール", "窓フィルム", "飛散防止フィルム",
        "アクセントクロス", "姿見", "ミラー", "タイル",
    ],
    "商談・工程": [
        "内覧会", "お引渡し", "採寸", "オプション会", "施主支給",
        "平面図", "展開図", "図面", "号室", "竣工",
    ],
}

# 実際に評価結果へ出た誤変換 → 正しい用語。**曖昧なものは入れない**
# （例「門」→「角」は門柱などと衝突するため、語単独ではなく前後を含む形にする）。
TRANSCRIPT_FIXES: dict[str, str] = {
    "入り墨": "入隅",
    "入り済み": "入隅",
    "入りすみ": "入隅",
    "出済み": "出隅",
    "出隅み": "出隅",
    # 「門」単独は「専門」等と衝突する（実データで19/20件が「専門」だった）ため、
    # 語単独では置換せず、誤変換が起きた言い回しごと直す。
    "門になる部分": "角になる部分",
    "エコガラス": "エコカラット",
    "エコカラー": "エコカラット",
}

# --- 営業特化AIペルソナ（評価者の人格）---
# 評価プロンプトの冒頭に置き、AIに「住宅営業のプロ」として振る舞わせる。
# --- 弊社の重点方針（全評価に反映する採点ポリシー）---
# 現場の最大課題：潜在ニーズを引き出す前に商品説明へ進んでしまい、見積に入れても外される。
# 対策：初回動線で関係値を築き、ニーズを自分ごと化させてから説明に入る。
SALES_POLICY = (
    "# 弊社の重点方針（採点に必ず反映する）\n"
    "現場の最大の課題は「お客様の潜在ニーズを引き出す前に、商品説明へ進んでしまう」こと。"
    "その結果、見積書に入れても後から外されてしまう。これを是正する評価を行う。\n"
    "次を厳しく見る：\n"
    "① 商品説明に入る前に、お客様の暮らし・不安・困りごと（潜在ニーズ）を引き出せたか\n"
    "② そのニーズを“お客様自身の言葉”で語らせ、自分ごとにできたか\n"
    "③ 説明が「引き出したニーズへの回答」になっているか（機能の羅列になっていないか）\n"
    "④ 初回の接点から関係値（なんでも相談できる空気）を築けたか\n"
    "重点商材（粗利が高く、受注率を上げたい）：コーティング／エコカラット／ダウンライト。"
    "これらは特に、お客様が『自分には必要だ』と納得した状態を作れているかを見る。\n"
    "★ニーズの引き出しが不十分なまま説明・見積提示に進んでいる場合は、"
    "説明がどれだけ流暢でも高評価にしないこと（見積から外される典型パターン）。"
)

SALES_AI_PERSONA = (
    "あなたは住宅営業のトップセールスであり、後輩を本気で伸ばすロープレコーチです。"
    "数百件の「理想の家」商談を成約させ、お客様が口に出さない本音・不安・疑問を、"
    "声のトーン・間・言い淀み・話題の回避から誰よりも敏感に読み取ります。"
    "コーチングの“言葉”は常にポジティブで具体的に伝えますが、"
    "“点数”は必ずお客様目線で厳格・正確につけ、甘い高得点は決して出しません。"
    "表面上うまく話せていても、お客様の裏のニーズ（秘密領域）を取りこぼしていれば、"
    "はっきりと見抜き、それを採点に反映します。"
)
