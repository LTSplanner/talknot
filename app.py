"""TalKnot（トークノット）— 営業商談・ロープレ評価 Web アプリ

Talk（話す）＋ Knot（結び目・絆）。
お客様との会話が弾み、絆が結ばれる商談へ導くための、ポジティブな振り返りツール。

起動: `streamlit run app.py`

GOOGLE_CLIENT_ID/SECRET が設定されていれば本物の Google 認証を、
未設定ならUI確認用のデモログインを使う。
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
import uuid
from pathlib import Path

import streamlit as st

# Streamlit Cloud では秘密情報を st.secrets（TOML）で渡す。config.settings は
# os.getenv で読むため、プロジェクト import より前に os.environ へ橋渡しする。
# ローカル（secrets.toml 無し）では st.secrets アクセスが例外になるので握りつぶす。
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ.setdefault(_k, _v)
except Exception:
    pass

from auth import google_oauth, persist, session  # noqa: E402
from config import settings  # noqa: E402
from core.models import EvaluationResult  # noqa: E402
from services import drive_sa, gemini_analyzer, google_drive, storage  # noqa: E402
from ui import components, theme  # noqa: E402

st.set_page_config(
    page_title="トークノット｜営業ロープレ評価",
    page_icon="🪢",
    layout="wide",
    initial_sidebar_state="auto",  # スマホでは自動で折りたたむ
)
theme.inject_css()


# --------------------------------------------------------------------------- #
# 認証
# --------------------------------------------------------------------------- #
def resolve_user() -> dict | None:
    """ログイン中ユーザーを返す。OAuth コールバックや保存Cookieがあれば処理する。"""
    if "user" in st.session_state:
        return st.session_state["user"]

    # ブラウザに保存したログイン（暗号化Cookie）から復元（14日間は再ログイン不要）
    saved = persist.load()
    if saved and saved.get("user"):
        st.session_state["user"] = saved["user"]
        if saved.get("creds"):
            st.session_state["credentials"] = saved["creds"]
        return saved["user"]

    if session.oauth_configured():
        try:
            user = google_oauth.handle_callback()
            if user:
                # 次回から再ログインを省くためCookieへ保存
                persist.save(user, st.session_state.get("credentials"))
            return user
        except google_oauth.DomainNotAllowedError as e:
            st.session_state["login_error"] = (
                f"`{e.email}` は許可されていないドメインです。"
                f"（許可: {', '.join(settings.ALLOWED_DOMAINS)}）"
            )
    return None


def render_login() -> None:
    components.hero(subtitle="お話が楽しくなる。お客様との絆が、結ばれる。")

    if err := st.session_state.pop("login_error", None):
        st.error(err)

    left, right = st.columns([3, 2])
    with left:
        st.markdown("#### 商談・ロープレ動画を、AIがポジティブに振り返ります")
        st.write(
            "Google Meet の録画や手持ちの動画から、声のトーン・間・発話比率まで分析。"
            "お客様の感情の動きをタイムスタンプ付きで可視化し、"
            "「もっと良くなる一言」を一緒に見つけます。"
        )
        st.caption(
            f"ログインできるのは `{', '.join(settings.ALLOWED_DOMAINS)}` "
            "ドメインのアカウントのみです。"
        )

    with right:
        st.markdown("<div class='tk-card'>", unsafe_allow_html=True)
        st.markdown("##### サインイン")
        if session.oauth_configured():
            google_oauth.login_button()
        else:
            st.warning("OAuth 未設定のためデモログインです（.env を設定すると本番認証）。")
            if st.button("デモでログイン", use_container_width=True):
                st.session_state["user"] = {
                    "name": "デモ ユーザー",
                    "email": (settings.ADMIN_EMAILS or ["demo@yourcompany.com"])[0],
                }
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# 評価フロー
# --------------------------------------------------------------------------- #
def _friendly_gemini_error(exc: Exception) -> str:
    """Gemini API のエラーを、利用者向けの日本語メッセージに翻訳する。"""
    code = getattr(exc, "code", None)
    if code == 429:
        return (
            "AI の無料利用枠（短時間あたりの上限）に達しました。"
            "1〜2分ほど待ってから、もう一度お試しください。"
            "長い動画は枠を多く消費します。商談の山場だけに短く切ると安定します。"
        )
    if code == 400:
        return (
            "動画が長すぎる・重すぎる可能性があります（AI が処理できる上限を超過）。"
            "動画を数分程度に短く切る、または短いクリップでお試しください。"
        )
    if code == 403:
        return "AI の利用権限エラーです（APIキー設定）。管理者にご連絡ください。"
    msg = getattr(exc, "message", "") or str(exc)
    return f"AI 解析でエラーが発生しました：{msg}"


def _analyze_worker(
    job_id: str,
    user_email: str,
    label: str,
    tmp_path: str | None = None,
    creds=None,
    file_id: str | None = None,
    suffix: str = ".mp4",
) -> None:
    """サーバーの裏で動く解析処理（st.* は一切使わない）。

    creds/file_id が渡された場合は、まずドライブから省メモリで録画をダウンロードする。
    画面を閉じてもこのスレッドは走り続け、完了したら履歴レコードを更新する。
    """
    try:
        if tmp_path is None:
            # ドライブから大容量録画をチャンク保存（メモリに全部載せない）
            fd, tmp_path = tempfile.mkstemp(suffix=suffix)
            os.close(fd)
            google_drive.download_to_path(creds, file_id, tmp_path)
        result = gemini_analyzer.analyze(
            tmp_path,
            storage.get_reference_talk(),
            storage.get_knowledge_base(),
        )
        storage.finish_evaluation(user_email, job_id, result, label)
        # 商談から抽出した弊社ナレッジを蓄積（使うほど評価が弊社仕様に賢くなる）
        storage.append_knowledge(result.knowledge)
    except Exception as exc:  # API/ダウンロードエラー等。失敗として履歴に残す。
        storage.fail_evaluation(user_email, job_id, _friendly_gemini_error(exc), label)
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


def _start_job(user: dict, label: str, **worker_kwargs) -> None:
    """背景ジョブを開始し、利用者に『閉じてOK』を伝える共通処理。"""
    job_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    storage.start_evaluation(user["email"], job_id, label)
    thread = threading.Thread(
        target=_analyze_worker,
        kwargs=dict(job_id=job_id, user_email=user["email"], label=label, **worker_kwargs),
        daemon=True,
    )
    thread.start()
    st.success(
        "✅ 評価を開始しました。解析はサーバーの裏で進みます。"
        "**この画面を閉じても大丈夫**です。"
    )
    st.info("結果は「🕘 評価履歴」タブに表示されます（長尺の録画は数分〜十数分かかります）。")


def _run_analysis(video_bytes: bytes, suffix: str, user: dict, label: str) -> None:
    """PC アップロード済みの動画を一時保存し、背景ジョブとして解析する。"""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(video_bytes)
        tmp_path = tmp.name
    _start_job(user, label, tmp_path=tmp_path)


def _start_drive_job(creds, file_id: str, user: dict, label: str) -> None:
    """ドライブの録画を『ダウンロードから解析まで』丸ごと背景で実行する。

    ボタンを押した後は、ダウンロード中でも画面を閉じてOK（サーバー側で続行）。
    """
    _start_job(user, label, creds=creds, file_id=file_id, suffix=".mp4")


def render_evaluate_tab(user: dict) -> None:
    st.markdown("##### 評価する商談を選ぶ")

    options = ["PC からアップロード", "自分のドライブから選択"]
    # サービスアカウント設定済みなら、管理者はメンバーのドライブを代理選択できる。
    member_mode = drive_sa.configured() and settings.is_admin(user.get("email"))
    if member_mode:
        options.append("メンバーのドライブから選択（代理）")

    source = st.radio(
        "動画ソース", options, horizontal=True, label_visibility="collapsed"
    )

    if source.startswith("PC"):
        uploaded = st.file_uploader(
            "動画・音声ファイル", type=["mp4", "mov", "m4a", "mp3", "wav"]
        )
        if uploaded and st.button("AI で評価する"):
            suffix = Path(uploaded.name).suffix or ".mp4"
            _run_analysis(uploaded.getvalue(), suffix, user, uploaded.name)
    elif source.startswith("メンバー"):
        _render_member_drive_picker(user)
    else:
        creds = session.get_credentials()
        if not creds:
            st.info("ドライブ連携には Google ログインが必要です（デモログインでは利用不可）。")
        else:
            _render_drive_picker(creds, user)


def _render_member_drive_picker(user: dict) -> None:
    """サービスアカウントで対象メンバーのドライブを代理閲覧して選択する。"""
    member = st.selectbox("評価するメンバー", settings.TARGET_ACCOUNTS)
    keyword = st.text_input(
        "ファイル名で絞り込み（任意）", placeholder="例: 商談 / Meet / 顧客名"
    )
    try:
        creds = drive_sa.impersonate(member)
        files = google_drive.list_videos(creds, name_contains=keyword.strip() or None)
    except Exception as e:
        st.error(
            f"メンバーのドライブにアクセスできませんでした：{e}\n\n"
            "ドメイン全体委任（DWD）の設定が未完了の可能性があります。"
            "docs/SETUP_SERVICE_ACCOUNT.md を確認してください。"
        )
        return

    if not files:
        st.info(f"{member} のドライブに動画が見つかりませんでした。")
        return

    st.caption(f"{member} のアクセス可能な動画：{len(files)} 件")
    labels = {f["id"]: f"{f['name']}　[{f.get('createdTime', '')[:10]}]" for f in files}
    file_id = st.selectbox("動画を選択", options=list(labels), format_func=lambda i: labels[i])
    if st.button("AI で評価する"):
        _start_drive_job(creds, file_id, user, f"{member}｜{labels[file_id]}")


def _render_drive_picker(creds, user: dict) -> None:
    keyword = st.text_input(
        "ファイル名で絞り込み（任意）", placeholder="例: 商談 / Meet / 顧客名",
    )
    try:
        files = google_drive.list_videos(creds, name_contains=keyword.strip() or None)
    except Exception as e:  # API エラーはユーザーに見せる
        st.error(f"ドライブの読み込みに失敗しました：{e}")
        return

    if not files:
        st.info(
            "アクセスできる動画が見つかりませんでした。\n\n"
            "Google の権限上、表示されるのは **あなたが所有 or あなたに共有された動画**、"
            "および **参加している共有ドライブ** の動画だけです。"
            "他メンバーの個人ドライブにある録画は、共有されるか共有ドライブに置かれるまで表示されません。"
        )
        return

    st.caption(f"アクセス可能な動画：{len(files)} 件")
    labels = {}
    for f in files:
        owner = f.get("owner", "")
        date = f.get("createdTime", "")[:10]
        labels[f["id"]] = f"{f['name']}　[{date}{('・' + owner) if owner else ''}]"
    file_id = st.selectbox(
        "動画を選択", options=list(labels), format_func=lambda i: labels[i]
    )
    if st.button("AI で評価する"):
        _start_drive_job(creds, file_id, user, labels[file_id])


def _reference_worker(
    job_id: str, label: str, tmp_path: str | None = None, creds=None, file_id: str | None = None
) -> None:
    """模範トーク動画を背景で文字起こしして蓄積する（st.* は使わない）。

    creds/file_id 指定時はドライブから省メモリでダウンロードしてから処理する。
    """
    own_tmp: str | None = None
    try:
        if tmp_path is None:
            fd, own_tmp = tempfile.mkstemp(suffix=".mp4")
            os.close(fd)
            google_drive.download_to_path(creds, file_id, own_tmp)
            tmp_path = own_tmp
        transcript = gemini_analyzer.transcribe_reference(tmp_path)
        if transcript:
            storage.finish_reference(job_id, transcript)
        else:
            storage.fail_reference(job_id, "文字起こし結果が空でした。")
    except Exception as exc:
        storage.fail_reference(job_id, _friendly_gemini_error(exc))
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


def _start_reference_job(label: str, **worker_kwargs) -> None:
    """模範トークの文字起こしを背景で開始する（押したら閉じてOK）。"""
    job_id = "ref_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    storage.start_reference_job(job_id, label)
    threading.Thread(
        target=_reference_worker,
        kwargs=dict(job_id=job_id, label=label, **worker_kwargs),
        daemon=True,
    ).start()
    st.success("✅ 模範トークの文字起こしを開始しました。**閉じてOK**。完了すると下の一覧に追加されます。")


def render_reference_tab(user: dict) -> None:
    st.markdown("##### 模範トーク")
    st.write(
        "複数の模範商談を登録すると、すべてが 🎯模範トーク視点の基準として積み重なります。"
        "動画は保存せず、文字起こしテキストだけを蓄積します（容量対策）。"
    )

    _render_reference_list(user)

    if not settings.is_admin(user.get("email")):
        st.caption("登録は管理者のみが行えます。")
        return

    st.divider()
    st.markdown("###### 模範トークを追加")

    sources = ["自分のドライブから選択", "テキストを直接入力", "PC からアップロード"]
    # サービスアカウント設定済みなら、基準アカウント（kkyoya@等）の代理取得も選べる。
    if drive_sa.configured() and settings.REFERENCE_ACCOUNTS:
        sources.append("基準アカウントのドライブから（代理）")
    source = st.radio("追加方法", sources, horizontal=True, key="ref_source")

    if source.startswith("自分のドライブ"):
        creds = session.get_credentials()
        if not creds:
            st.info("ドライブ連携には Google ログインが必要です（デモログインでは利用不可）。")
        else:
            _render_reference_own_drive_picker(creds)
    elif source.startswith("テキスト"):
        text = st.text_area("模範トーク（テキスト）", height=140, key="ref_text")
        if st.button("追加する", key="ref_add_text") and text.strip():
            storage.add_reference_talk(text, label="手入力")
            st.rerun()
    elif source.startswith("PC"):
        file = st.file_uploader("動画/テキスト", type=["mp4", "mov", "txt"], key="ref_upload")
        if file is not None and st.button("追加する", key="ref_add_file"):
            if Path(file.name).suffix.lower() == ".txt":
                storage.add_reference_talk(
                    file.getvalue().decode("utf-8", errors="ignore"), label=file.name
                )
                st.rerun()
            else:
                with tempfile.NamedTemporaryFile(
                    suffix=Path(file.name).suffix or ".mp4", delete=False
                ) as tmp:
                    tmp.write(file.getvalue())
                    tmp_path = tmp.name
                _start_reference_job(file.name, tmp_path=tmp_path)
    else:
        _render_reference_drive_picker()


def _render_reference_own_drive_picker(creds) -> None:
    """ログイン中ユーザー自身のドライブから模範動画を選び、背景で文字起こし・蓄積する。"""
    keyword = st.text_input(
        "ファイル名で絞り込み（任意）",
        placeholder="例: 商談 / Meet / 顧客名",
        key="refown_keyword",
    )
    try:
        files = google_drive.list_videos(creds, name_contains=keyword.strip() or None)
    except Exception as e:
        st.error(f"ドライブの読み込みに失敗しました：{e}")
        return
    if not files:
        st.info(
            "アクセスできる動画が見つかりませんでした。"
            "あなたが所有 or 共有された動画、参加中の共有ドライブの動画が対象です。"
        )
        return
    labels = {}
    for f in files:
        date = f.get("createdTime", "")[:10]
        labels[f["id"]] = f"{f['name']}　[{date}]"
    file_id = st.selectbox(
        "模範にする動画を選択",
        options=list(labels),
        format_func=lambda i: labels[i],
        key="refown_file",
    )
    if st.button("この動画を模範トークとして追加", key="refown_register"):
        _start_reference_job(labels[file_id].split("　")[0], creds=creds, file_id=file_id)


def _render_reference_list(user: dict) -> None:
    items = storage.list_reference_talks()
    if not items:
        st.caption("まだ模範トークがありません。")
        return
    if any(it.get("status") == "processing" for it in items):
        if st.button("🔄 最新の状態に更新", key="ref_refresh"):
            st.rerun()
    is_admin = settings.is_admin(user.get("email"))
    for it in reversed(items):
        status = it.get("status", "done")
        badge = _STATUS_BADGE.get(status, "✅ 完了")
        title = it.get("label") or it.get("added_at", "")
        with st.expander(f"{badge}　{title}"):
            if status == "processing":
                st.caption("AI が文字起こし中です。少し待って更新してください。")
            elif status == "error":
                st.error(it.get("error", "文字起こしに失敗しました。"))
            else:
                body = it.get("text", "")
                st.code(body[:800] + ("…" if len(body) > 800 else ""))
            if is_admin and st.button("削除", key=f"ref_del_{it.get('id')}"):
                storage.delete_reference_talk(it.get("id"))
                st.rerun()


def _render_reference_drive_picker() -> None:
    """基準アカウントのドライブから動画を選び、模範トークとして背景で文字起こし・蓄積する。"""
    account = st.selectbox(
        "基準アカウント", settings.REFERENCE_ACCOUNTS, key="ref_account"
    )
    keyword = st.text_input(
        "ファイル名で絞り込み（任意）",
        placeholder="例: 商談 / Meet / 顧客名",
        key="ref_keyword",
    )
    try:
        creds = drive_sa.impersonate(account)
        files = google_drive.list_videos(creds, name_contains=keyword.strip() or None)
    except Exception as e:
        st.error(
            f"{account} のドライブにアクセスできませんでした：{e}\n\n"
            "ドメイン全体委任（DWD）の設定が未完了の可能性があります。"
            "docs/SETUP_SERVICE_ACCOUNT.md を確認してください。"
        )
        return

    if not files:
        st.info(f"{account} のドライブに動画が見つかりませんでした。")
        return

    labels = {f["id"]: f"{f['name']}　[{f.get('createdTime', '')[:10]}]" for f in files}
    file_id = st.selectbox(
        "模範にする動画を選択",
        options=list(labels),
        format_func=lambda i: labels[i],
        key="ref_file",
    )
    if st.button("この動画を模範トークとして追加", key="ref_register"):
        name = labels[file_id].split("　")[0]
        _start_reference_job(f"{account}｜{name}", creds=creds, file_id=file_id)


_STATUS_BADGE = {
    "processing": "⏳ 処理中",
    "done": "✅ 完了",
    "error": "❌ 失敗",
}


def render_history_tab(user: dict) -> None:
    st.markdown("##### 評価履歴")
    records = storage.list_evaluations(user["email"])
    if not records:
        st.caption("まだ評価履歴がありません。")
        return

    if any(r.get("status") == "processing" for r in records):
        st.info("⏳ 処理中の評価があります。完了したら下に結果が出ます。")
    if st.button("🔄 最新の状態に更新"):
        st.rerun()

    for rec in records:
        status = rec.get("status", "done")
        badge = _STATUS_BADGE.get(status, "✅ 完了")
        with st.expander(f"{badge}　{rec.get('saved_at', '')}　{rec.get('label', '')}"):
            if status == "processing":
                st.caption("AI が解析中です。少し待って「🔄 最新の状態に更新」を押してください。")
            elif status == "error":
                st.error(rec.get("error", "解析に失敗しました。"))
            elif rec.get("result"):
                components.evaluation_result(EvaluationResult.from_dict(rec["result"]))


_CATEGORY_LABELS = {
    "product": "🏠 商品知識",
    "rule": "📏 社内ルール",
    "technique": "🗣️ トーク技術",
}


def render_knowledge_tab(user: dict) -> None:
    st.markdown("##### 弊社ナレッジ（AIが前提にする社内知識）")
    st.write(
        "AI は2種類の社内知識を前提に評価します："
        "**① 整備済みの社内資料**（商品・料金・サービス・FAQ）と、"
        "**② 商談から自動で学んだ知識**（商品知識・社内ルール・トーク技術）。"
        "これにより評価が弊社仕様になります。（個人情報は含めません）"
    )
    from services import sheets_knowledge
    if sheets_knowledge.configured():
        st.caption("💾 共有ドライブのスプレッドシートに永続保存されています（再起動でも消えません）。")
    else:
        st.caption("⚠️ 現在はアプリ内に一時保存です（再起動で消える可能性）。共有ドライブ保存は docs/SETUP_KNOWLEDGE_SHEET.md を設定すると有効になります。")

    # ① 整備済みの社内ナレッジ資料（商品・料金・サービス・FAQ）
    doc = storage.get_knowledge_doc()
    st.divider()
    st.markdown("**📚 社内ナレッジ資料（商品・料金・サービス・FAQ）**")
    if doc:
        st.caption(f"取り込み済み：約 {len(doc):,} 文字。毎回の評価で AI がこの資料を前提に判定します。")
        with st.expander("資料の中身を確認する"):
            st.text(doc[:4000] + ("\n…（以下省略）" if len(doc) > 4000 else ""))
    else:
        st.caption("まだ取り込まれていません。下のボタンでドライブの資料フォルダから取り込めます（管理者）。")

    if settings.is_admin(user.get("email")):
        _render_knowledge_doc_admin(user, has_doc=bool(doc))

    st.divider()
    # ② 商談から AI が自動抽出して蓄積する知識
    st.markdown("**🧠 商談から学んだ知識（自動蓄積）**")
    items = storage.get_knowledge_items()
    if not items:
        st.caption("まだ蓄積された知識はありません。商談を評価すると貯まっていきます。")
    else:
        st.caption(f"蓄積件数：{len(items)} 件")
        for cat, label in _CATEGORY_LABELS.items():
            group = [i["point"] for i in items if i.get("category") == cat]
            if not group:
                continue
            st.markdown(f"**{label}**（{len(group)}件）")
            for p in group:
                st.markdown(f"- {p}")
        if settings.is_admin(user.get("email")):
            if st.button("🗑️ 蓄積した知識をすべて消去", key="clear_knowledge"):
                storage.clear_knowledge()
                st.success("弊社ナレッジを消去しました。")
                st.rerun()


def _render_knowledge_doc_admin(user: dict, has_doc: bool) -> None:
    """管理者向け：ドライブの資料フォルダから社内ナレッジ資料を取り込む／消去する。"""
    from services import google_drive

    with st.expander("📁 資料フォルダから取り込み・更新（管理者）"):
        st.caption(
            "社内の質疑応答AI用に整備した資料フォルダから、商品・料金・サービス・FAQ を取り込みます。"
            "巨大な統合シート・生CSV・メール書庫は自動で除外します。"
        )
        folder_id = st.text_input(
            "資料フォルダ ID", value=settings.KNOWLEDGE_FOLDER_ID, key="kdoc_folder"
        )
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("📥 取り込む / 更新する", key="kdoc_import", use_container_width=True):
                creds = session.get_credentials()
                if not creds:
                    st.error("ドライブ連携の認証が必要です。一度ログインし直してください。")
                else:
                    with st.spinner("資料を読み込んでいます…"):
                        try:
                            svc = google_drive._service(creds)
                            text, included, skipped = google_drive.export_knowledge_folder(
                                svc, folder_id.strip()
                            )
                            if not text:
                                st.warning("取り込める資料が見つかりませんでした（フォルダの共有設定をご確認ください）。")
                            else:
                                storage.set_knowledge_doc(text)
                                st.success(
                                    f"取り込み完了：{len(included)} 件・約 {len(text):,} 文字を保存しました。"
                                )
                                st.caption("取り込んだ資料：" + " / ".join(included))
                                st.rerun()
                        except Exception as exc:  # noqa: BLE001
                            st.error(f"取り込みに失敗しました：{exc}")
        with col_b:
            if has_doc and st.button("🗑️ 社内資料を消去", key="kdoc_clear", use_container_width=True):
                storage.clear_knowledge_doc()
                st.success("社内ナレッジ資料を消去しました。")
                st.rerun()


def render_app(user: dict) -> None:
    components.sidebar(user)
    components.hero(compact=True)

    evaluate, reference, knowledge, history, about = st.tabs(
        ["🎥 商談を評価する", "⭐ 模範トーク", "🧠 弊社ナレッジ", "🕘 評価履歴", "📊 評価項目について"]
    )
    with evaluate:
        render_evaluate_tab(user)
    with reference:
        render_reference_tab(user)
    with knowledge:
        render_knowledge_tab(user)
    with history:
        render_history_tab(user)
    with about:
        st.markdown("##### TalKnot が見る 5 つの視点")
        components.criteria_overview()


def main() -> None:
    user = resolve_user()
    if user is None:
        render_login()
    else:
        render_app(user)


if __name__ == "__main__":
    main()
