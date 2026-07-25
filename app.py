"""KNOTE（ノート）— 営業商談・ロープレ評価 Web アプリ

Talk（話す）＋ Knot（結び目・絆）。
お客様との会話が弾み、絆が結ばれる商談へ導くための、ポジティブな振り返りツール。

起動: `streamlit run app.py`

GOOGLE_CLIENT_ID/SECRET が設定されていれば本物の Google 認証を、
未設定ならUI確認用のデモログインを使う。
"""
from __future__ import annotations

import gc
import os
import random
import shutil
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
from services import drive_sa, gemini_analyzer, google_drive, storage, usage_log  # noqa: E402
from ui import components, theme  # noqa: E402

_BRAND_ICON = Path(__file__).parent / "assets" / "knote_icon.png"

st.set_page_config(
    page_title="KNOTE（ノート）｜営業ロープレ評価",
    page_icon=str(_BRAND_ICON) if _BRAND_ICON.exists() else "📓",
    layout="wide",
    initial_sidebar_state="auto",  # スマホでは自動で折りたたむ
)
theme.inject_css()


def _declare_japanese_page() -> None:
    """ページ言語を日本語と宣言し、Chromeの自動翻訳による誤訳を防ぐ。

    Streamlit は <html lang="en"> を出力するため、Chrome が英語ページと誤認して
    日本語へ「翻訳」し、ブランド名(KNOTE→注記)や本文(可視化→解決)まで書き換えてしまう。
    """
    import streamlit.components.v1 as _c

    # lang=ja だけでは「手動翻訳」を止められず、Google翻訳がDOMを書き換えると
    # React が removeChild で落ちる（有名な衝突）。notranslate と meta を明示して
    # 翻訳対象から完全に外す。
    _c.html(
        "<script>try{const d=window.parent.document;const h=d.documentElement;"
        "h.lang='ja';h.setAttribute('translate','no');h.classList.add('notranslate');"
        "if(!d.querySelector('meta[name=\"google\"]')){"
        "var m=d.createElement('meta');m.name='google';m.content='notranslate';"
        "(d.head||h).appendChild(m);}"
        "}catch(e){}</script>",
        height=0,
    )


_declare_japanese_page()


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
        except Exception:
            # OAuth周りの想定外エラーでもアプリは落とさず、ログインし直しに倒す。
            st.session_state["login_error"] = (
                "ログイン処理でエラーが発生しました。お手数ですが、もう一度ログインしてください。"
            )
            try:
                st.query_params.clear()
            except Exception:
                pass
    return None


def render_login() -> None:
    components.hero()

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


# 同時に走る重い解析の数を制限する。無料枠（RAM 約1GB）で複数人が同時に解析しても
# メモリが急騰してコンテナが落ちないよう、超過分は自動的に順番待ち（キュー）になる。
_ANALYSIS_SLOTS = threading.BoundedSemaphore(settings.MAX_CONCURRENT_ANALYSES)


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
    同時実行はセマフォで制限し、混雑時は順番待ちにしてメモリ超過の鯖落ちを防ぐ。
    """
    try:
        # 重い処理（ダウンロード＋解析）だけを同時実行数の枠内で行う。
        with _ANALYSIS_SLOTS:
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
        usage_log.log("evaluate", user_email=user_email, ok=True, source="streamlit-bg")
    except Exception as exc:  # API/ダウンロードエラー等。失敗として履歴に残す。
        storage.fail_evaluation(user_email, job_id, _friendly_gemini_error(exc), label)
        usage_log.log("evaluate", user_email=user_email, ok=False, source="streamlit-bg")
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
        gc.collect()  # 大きなバッファを早めに解放してメモリを戻す


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
    st.info(
        "結果は「🕘 評価履歴」タブに表示されます（長尺の録画は数分〜十数分かかります）。"
        "混雑時は順番待ちになることがあります。"
    )


def _run_analysis(uploaded, suffix: str, user: dict, label: str) -> None:
    """PC アップロード済みの動画を一時保存し、背景ジョブとして解析する。

    `uploaded.getvalue()`（全体をもう一度メモリにコピー）を避け、ディスクへ
    チャンクで書き出してピークメモリを抑える。
    """
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        uploaded.seek(0)
        shutil.copyfileobj(uploaded, tmp, length=8 * 1024 * 1024)
        tmp_path = tmp.name
    _start_job(user, label, tmp_path=tmp_path)


def _start_drive_job(creds, file_id: str, user: dict, label: str) -> None:
    """ドライブの録画を『ダウンロードから解析まで』丸ごと背景で実行する。

    ボタンを押した後は、ダウンロード中でも画面を閉じてOK（サーバー側で続行）。
    """
    _start_job(user, label, creds=creds, file_id=file_id, suffix=".mp4")


def render_evaluate_tab(user: dict) -> None:
    st.markdown("##### 評価する商談を選ぶ")

    options = ["📅 カレンダーの商談から", "自分のドライブから選択", "PC からアップロード"]
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
            _run_analysis(uploaded, suffix, user, uploaded.name)
    elif source.startswith("メンバー"):
        _render_member_drive_picker(user)
    elif source.startswith("📅"):
        creds = session.get_credentials()
        if not creds:
            st.info("カレンダー連携には Google ログインが必要です（デモログインでは利用不可）。")
        else:
            _render_calendar_picker(creds, user)
    else:
        creds = session.get_credentials()
        if not creds:
            st.info("ドライブ連携には Google ログインが必要です（デモログインでは利用不可）。")
        else:
            _render_drive_picker(creds, user)


def _render_calendar_picker(creds, user: dict) -> None:
    """自分のGoogleカレンダーの商談（Meet）予定から選び、その録画を評価する。"""
    from services import google_calendar

    only_meet = st.checkbox("Meet（オンライン商談）のみ表示", value=True, key="cal_meet_only")
    try:
        events = google_calendar.list_meetings(creds)
    except Exception as e:  # スコープ不足 / API無効 など
        msg = str(e)
        low = msg.lower()
        api_disabled = ("accessnotconfigured" in low or "service_disabled" in low
                        or "has not been used in project" in low or "it is disabled" in low)
        scope_missing = ("insufficient" in low or "insufficientpermissions" in low
                         or "access_token_scope_insufficient" in low
                         or ("scope" in low and not api_disabled))
        if api_disabled:
            st.error(
                "Google カレンダー API がプロジェクト側で無効のため連携できません。"
                "（これはログインし直しても直りません）\n\n"
                "Google Cloud Console → 「API とサービス」→ Calendar API を **有効化** すると使えます。"
            )
            st.caption(f"詳細：{msg[:200]}")
        elif scope_missing:
            st.warning(
                "カレンダー連携がまだ有効ではありません。**一度ログアウト→再ログイン**すると、"
                "カレンダーの利用許可を求められて有効になります。"
            )
            if st.button("🔓 ログアウトして連携し直す", key="cal_relogin"):
                from auth import persist, session as _sess
                persist.clear(); _sess.logout(); st.rerun()
        else:
            st.error(f"カレンダーの読み込みに失敗しました：{msg[:200]}")
        return

    if only_meet:
        events = [e for e in events if e.get("has_meet")]
    if not events:
        st.info("直近60日に、対象の商談予定が見つかりませんでした。")
        return

    def _label(e):
        d = e.get("start", "").replace("T", " ")[:16]
        meet = "🟢Meet" if e.get("has_meet") else "　"
        return f"{d}　{meet}　{e.get('summary','')[:44]}"

    idx = st.selectbox(
        "商談予定を選ぶ（新しい順）", options=list(range(len(events))),
        format_func=lambda i: _label(events[i]), key="cal_event",
    )
    ev = events[idx]

    with st.spinner("この商談の録画をドライブから探しています…"):
        rec = google_calendar.find_recording(creds, ev.get("summary", ""), ev.get("start_date", ""))

    if rec:
        st.success(f"🎥 録画が見つかりました：{rec.get('name','')[:60]}")
        st.caption(f"作成日：{rec.get('createdTime','')[:10]}")
        if st.button("AI で評価する", key="cal_eval", use_container_width=True):
            _start_drive_job(creds, rec["id"], user, ev.get("summary", "")[:60])
    else:
        st.warning(
            "この予定に対応する録画がドライブ内に見つかりませんでした。\n\n"
            "・会議後、録画が生成されるまで数分〜十数分かかります。\n"
            "・録画があなたのドライブ（あなたが主催）に保存されている必要があります。\n"
            "・見つからない場合は「自分のドライブから選択」で直接お選びください。"
        )


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
        # 自分が所有する（自分のアドレスに紐づく）動画のみ。他人の共有動画は出さない。
        files = google_drive.list_videos(
            creds, name_contains=keyword.strip() or None, owned_only=True
        )
    except Exception as e:  # API エラーはユーザーに見せる
        st.error(f"ドライブの読み込みに失敗しました：{e}")
        return

    # 念のための二重防御：所有者がログイン中ユーザー本人のものだけに限定する。
    me = (user.get("email") or "").lower()
    if me:
        files = [f for f in files if (f.get("owner") or "").lower() in ("", me)]

    if not files:
        st.info(
            "あなたが所有する動画が見つかりませんでした。\n\n"
            "ここに表示されるのは **あなた自身のドライブにある（あなたが所有する）動画だけ** です。"
            "他メンバーの商談動画は、たとえ共有されていても表示されません（プライバシー保護のため）。"
        )
        return

    st.caption(f"あなたが所有する動画：{len(files)} 件")
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
        files = google_drive.list_videos(
            creds, name_contains=keyword.strip() or None, owned_only=True
        )
    except Exception as e:
        st.error(f"ドライブの読み込みに失敗しました：{e}")
        return
    if not files:
        st.info(
            "あなたが所有する動画が見つかりませんでした。"
            "ここには **あなた自身のドライブにある動画だけ** が表示されます。"
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


def _render_practice_overview(all_records: list[dict]) -> None:
    """管理者向け：誰が・どれだけ・いつロープレしたかの実施状況サマリ。"""
    stats: dict[str, dict] = {}
    for r in all_records:
        who = r.get("user_email", "") or "(不明)"
        s = stats.setdefault(who, {"roleplay": 0, "meeting": 0, "last": ""})
        if str(r.get("label", "")).startswith("🎙️"):
            s["roleplay"] += 1
        else:
            s["meeting"] += 1
        when = r.get("saved_at", "")
        if when > s["last"]:
            s["last"] = when
    if not stats:
        return
    st.markdown("**📊 メンバー別の実施状況**")
    rows = [
        {
            "メンバー": who.split("@")[0],
            "🎙️ロープレ": v["roleplay"],
            "🎥商談評価": v["meeting"],
            "最終実施": v["last"] or "-",
        }
        for who, v in sorted(stats.items(), key=lambda kv: -kv[1]["roleplay"])
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _is_roleplay(rec: dict) -> bool:
    return str(rec.get("label", "")).startswith("🎙️")


def _avg_score(result: dict | None) -> float | None:
    """1件の評価から、営業プロ視点の平均点（1〜5）を返す。"""
    if not result:
        return None
    scores = result.get("scores") or []
    vals = [int(s.get("sales_score") or 0) for s in scores if s.get("sales_score")]
    return round(sum(vals) / len(vals), 2) if vals else None


def _render_member_dashboard(who: str, records: list[dict]) -> None:
    """メンバー個人の成長ダッシュボード（推移グラフ＋左右2カラム一覧）。"""
    done = [r for r in records if r.get("status") == "done" and r.get("result")]
    roleplay = [r for r in records if _is_roleplay(r)]
    meeting = [r for r in records if not _is_roleplay(r)]

    # --- サマリ指標 ---
    st.markdown(f"#### 📈 {who.split('@')[0]} さんの成長ダッシュボード")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🎙️ ロープレ", f"{len(roleplay)} 回")
    m2.metric("🎥 商談評価", f"{len(meeting)} 回")
    scored = [(_avg_score(r["result"]), r) for r in done]
    scored = [(v, r) for v, r in scored if v is not None]
    scored.sort(key=lambda x: x[1].get("saved_at", ""))
    if scored:
        first, last = scored[0][0], scored[-1][0]
        m3.metric("平均スコア（最新）", f"{last:.2f} / 5", delta=f"{last - first:+.2f}")
        m4.metric("最終実施", (scored[-1][1].get("saved_at", "")[:10]) or "-")

    # --- 成長推移（折れ線）＋ 実行推移（棒）＋ 直近の項目別（円/棒）---
    import pandas as pd

    if scored:
        st.markdown("**スコアの推移（実施した順・営業プロ視点の平均）**")
        df = pd.DataFrame({
            "実施日時": [r.get("saved_at", "") for _, r in scored],
            "スコア": [v for v, _ in scored],
        }).set_index("実施日時")
        st.line_chart(df, height=240)

    g1, g2 = st.columns(2)
    with g1:
        st.markdown("**実行回数（種類別）**")
        st.bar_chart(pd.DataFrame(
            {"回数": [len(roleplay), len(meeting)]},
            index=["🎙️ロープレ", "🎥商談評価"],
        ), height=240, color="#6C5CE7")
    with g2:
        # 直近の完了評価の「5項目 × 営業プロ視点」を棒で
        latest = scored[-1][1] if scored else None
        st.markdown("**直近評価の項目別スコア**")
        if latest and latest.get("result"):
            rows = {}
            for s in latest["result"].get("scores", []):
                c = settings.CRITERIA_BY_KEY.get(s.get("key", ""))
                rows[(c.title if c else s.get("key", ""))] = int(s.get("sales_score") or 0)
            if rows:
                st.bar_chart(pd.DataFrame({"点": rows.values()}, index=list(rows)),
                             height=240, color="#FF6F61")
        else:
            st.caption("完了した評価がまだありません。")

    # --- 左：ロープレ ／ 右：商談評価 の一覧 ---
    st.divider()
    left, right = st.columns(2)
    with left:
        st.markdown(f"##### 🎙️ 1人ロープレ（{len(roleplay)}）")
        _render_record_list(roleplay, "rp")
    with right:
        st.markdown(f"##### 🎥 商談評価（{len(meeting)}）")
        _render_record_list(meeting, "mt")


def _render_record_list(records: list[dict], key: str) -> None:
    """評価カードの一覧（ダッシュボードの左右カラム用）。"""
    if not records:
        st.caption("まだありません。")
        return
    for i, rec in enumerate(records):
        status = rec.get("status", "done")
        badge = _STATUS_BADGE.get(status, "✅ 完了")
        sc = _avg_score(rec.get("result"))
        sc_tag = f"　{sc:.1f}/5" if sc is not None else ""
        title = str(rec.get("label", "")).replace("🎙️1人ロープレ｜", "")
        with st.expander(f"{badge}{sc_tag}　{rec.get('saved_at','')[5:16]}　{title[:26]}"):
            if status == "error":
                st.error(rec.get("error", "解析に失敗しました。"))
            elif rec.get("result"):
                components.evaluation_result(EvaluationResult.from_dict(rec["result"]))
            else:
                st.caption("処理中です。")


def render_history_tab(user: dict) -> None:
    st.markdown("##### 評価履歴")

    is_admin = settings.is_admin(user.get("email"))
    records = storage.list_evaluations(user["email"])

    if is_admin:
        show_all = st.toggle("🛡️ 全メンバーの履歴を見る（管理者）", value=False, key="hist_all")
        if show_all:
            all_records = storage.list_all_evaluations()
            _render_practice_overview(all_records)
            members = ["全員"] + sorted({r.get("user_email", "") for r in all_records if r.get("user_email")})
            who = st.selectbox("メンバーで絞り込み", members, key="hist_member")
            if who != "全員":
                # 個人を選んだら成長ダッシュボード（推移グラフ＋左右2カラム一覧）
                _render_member_dashboard(who, [r for r in all_records if r.get("user_email") == who])
                return
            records = all_records
            st.caption(f"表示中：{len(records)} 件（管理者として全メンバーを閲覧しています）")

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
        owner = rec.get("user_email", "")
        who_tag = (
            f"　👤{owner.split('@')[0]}"
            if is_admin and owner and owner != user.get("email") else ""
        )
        with st.expander(
            f"{badge}　{rec.get('saved_at', '')}{who_tag}　{rec.get('label', '')}"
        ):
            if status == "processing":
                st.caption("AI が解析中です。少し待って「🔄 最新の状態に更新」を押してください。")
            elif status == "error":
                st.error(rec.get("error", "解析に失敗しました。"))
            elif rec.get("result"):
                components.evaluation_result(EvaluationResult.from_dict(rec["result"]))


def _customer_bubble(text: str, ctype: str) -> None:
    """お客様のセリフを、アバター＋吹き出しで『会話している雰囲気』に表示する。"""
    face, name = ("🙎", "まだ何も決めていないお客様") if ctype == "未検討" else \
                 ("🧑", "すでに検討中のお客様")
    st.markdown(
        f"""
        <div style="display:flex;gap:.9rem;align-items:flex-start;margin:.6rem 0 .2rem">
          <div style="flex:none;width:64px;height:64px;border-radius:50%;
                      background:linear-gradient(135deg,#FFE7E2,#EDE9FF);
                      display:flex;align-items:center;justify-content:center;font-size:2rem;
                      box-shadow:0 2px 10px rgba(0,0,0,.08);animation:tkbob 2.6s ease-in-out infinite">
            {face}
          </div>
          <div style="flex:1">
            <div style="font-size:.78rem;color:#8C8794;margin-bottom:.2rem">{name}</div>
            <div style="position:relative;background:#fff;border:1px solid #EFE9F5;
                        border-radius:14px;padding:.8rem 1rem;white-space:pre-wrap;
                        line-height:1.75;font-size:1.02rem;
                        box-shadow:0 2px 12px rgba(0,0,0,.06)">{_esc(text)}</div>
          </div>
        </div>
        <style>@keyframes tkbob{{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(-4px)}}}}</style>
        """,
        unsafe_allow_html=True,
    )


def _speak(text: str, key: str, auto: bool = False) -> None:
    """お客様のセリフを読み上げる。30〜40代女性の音声・API費用ゼロ。

    - `auto=False`（既定）: 「🔊 もう一度」ボタンを押したときだけ再生する。
    - `auto=True`: この要素がマウントされた瞬間に **一度だけ** 自動再生する。
      二重再生は Python 側の spoken フラグで防ぐ（auto=True を渡すのは
      「開始後・そのターンに初めて来た時」だけ）。タブを開いただけでは喋らない。
    """
    import json as _json

    import streamlit.components.v1 as st_components

    payload = _json.dumps(text)
    auto_js = "setTimeout(speak, 80);" if auto else "/* 自動再生しない */"
    st_components.html(
        f"""
        <button id="sp{key}" style="cursor:pointer;border:1px solid #6C5CE7;color:#6C5CE7;
          background:#fff;border-radius:999px;padding:.4rem 1rem;font-size:.9rem;font-weight:600">
          🔊 もう一度きく
        </button>
        <script>
        (function() {{
          const text = {payload};
          const synth = (window.parent && window.parent.speechSynthesis) || window.speechSynthesis;
          const MALE = ["Otoya", "Ichiro", "Hattori", "Daichi", "Naoki", "Male"];
          function pickVoice() {{
            let vs = synth.getVoices().filter(v => v.lang && v.lang.toLowerCase().indexOf("ja") === 0);
            if (!vs.length) return null;
            const female = vs.filter(v => !MALE.some(m => (v.name || "").indexOf(m) >= 0));
            if (female.length) vs = female;
            const pref = ["Google 日本語", "Kyoko", "O-Ren", "Nanami", "Ayumi", "Haruka", "Sayaka"];
            for (const p of pref) {{ const hit = vs.find(v => v.name && v.name.indexOf(p) >= 0); if (hit) return hit; }}
            return vs[0];
          }}
          function speak() {{
            try {{
              synth.cancel();
              const voice = pickVoice();
              const chunks = text.split(/(?<=[。！？\\n])/).filter(s => s.trim());
              chunks.forEach(function(c) {{
                const u = new SpeechSynthesisUtterance(c.trim());
                u.lang = "ja-JP"; u.rate = 1.08; u.pitch = 0.88; u.volume = 1.0;
                if (voice) u.voice = voice;
                synth.speak(u);
              }});
            }} catch (e) {{}}
          }}
          document.getElementById("sp{key}").onclick = speak;
          if (synth.onvoiceschanged !== undefined) {{ synth.onvoiceschanged = pickVoice; }}
          {auto_js}
        }})();
        </script>
        """,
        height=46,
    )


def _esc(text: str) -> str:
    """HTML として安全に表示するためのエスケープ（改行はCSSで保持する）。"""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _roleplay_worker(
    job_id: str, user_email: str, label: str,
    audio_turns: list, scenario_lines: list, focus: str | None = None,
) -> None:
    """1人ロープレの録音をまとめて1回だけ Gemini で評価する（背景実行）。"""
    try:
        with _ANALYSIS_SLOTS:
            result = gemini_analyzer.analyze_roleplay(
                audio_turns, scenario_lines,
                storage.get_talk_script() or None,
                storage.get_knowledge_base(),
                focus=focus,
                persona=storage.get_customer_persona(),
            )
        storage.finish_evaluation(user_email, job_id, result, label)
        storage.append_knowledge(result.knowledge)
        usage_log.log("roleplay", user_email=user_email, ok=True, source="streamlit-bg")
    except Exception as exc:  # noqa: BLE001
        storage.fail_evaluation(user_email, job_id, _friendly_gemini_error(exc), label)
        usage_log.log("roleplay", user_email=user_email, ok=False, source="streamlit-bg")
    finally:
        gc.collect()


def _session_turns(scenario: dict) -> list[dict]:
    """台本ターンを取得し、`variants`（切り口違いの雑談パターン）があれば
    セッション内で固定した1つに差し替えて返す。

    - 選出はセッション毎に一度だけ（キー rp_variant_{scenario_id}_{turn_index}）。
      同一セッションのリランでは選び直さないので、お客様セリフ表示・音声再生・AI評価が一致する。
      リセット（rp_ 接頭辞のキーを一括削除）や別単元では選び直される。
    - 管理者の overrides が入っているフィールドは variants より優先する（編集を尊重）。
    """
    turns = storage.persona_flavored_turns(scenario)
    sid = scenario.get("id", "")
    overrides = storage.get_scenario_overrides().get(sid, {})
    for idx, t in enumerate(turns):
        variants = t.get("variants")
        if not (isinstance(variants, list) and variants):
            continue
        key = f"rp_variant_{sid}_{idx}"
        pick = st.session_state.get(key)
        if not isinstance(pick, int) or not (0 <= pick < len(variants)):
            pick = random.randrange(len(variants))
            st.session_state[key] = pick
        v = variants[pick]
        o = overrides.get(str(idx), {}) if isinstance(overrides, dict) else {}
        cust_overridden = bool((o.get("customer") or "").strip())
        if not cust_overridden:
            t["customer"] = str(v.get("customer", t.get("customer", "")))
        if not (o.get("hint") or "").strip():
            t["hint"] = str(v.get("hint", t.get("hint", "")))
        # 往復ロープレ用：dialog（お客様の複数発話）を chosen variant から持たせる。
        # 管理者が第一声を上書きしている場合は、そちらを尊重して単発フローにする。
        dialog = v.get("dialog")
        if (not cust_overridden and isinstance(dialog, list)
                and len([d for d in dialog if str(d).strip()]) >= 2):
            t["dialog"] = [str(d) for d in dialog if str(d).strip()]
        t.pop("variants", None)
    return turns


def _start_roleplay_job(user: dict, scenario: dict, audio_turns: list,
                        scenario_lines: list | None = None) -> None:
    job_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    label = f"🎙️1人ロープレ｜{scenario.get('title','')}"
    storage.start_evaluation(user["email"], job_id, label)
    # 録音1件ごとに対応づけた お客様セリフ（往復含む）を優先。無い/長さ不一致なら
    # ターン第一声から再構成（後方互換のフォールバック）。
    if scenario_lines and len(scenario_lines) == len(audio_turns):
        lines = list(scenario_lines)
    else:
        lines = [t["customer"] for t in _session_turns(scenario)]
    threading.Thread(
        target=_roleplay_worker,
        kwargs=dict(job_id=job_id, user_email=user["email"], label=label,
                    audio_turns=audio_turns, scenario_lines=lines,
                    focus=scenario.get("focus")),
        daemon=True,
    ).start()


def _reset_roleplay() -> None:
    for k in [k for k in st.session_state if str(k).startswith("rp_")]:
        del st.session_state[k]


def _roleplay_undo_last() -> bool:
    """直前に保存した1件の録音を取り消し、そのターン（往復なら会話ステップ）へ戻す。

    自動進行で「今の録音をやり直す」ために使う。ナビ用スタック `rp_nav` の末尾を1つ戻し、
    音声/対応セリフ/カンペ使用の各リストも1件ずつ巻き戻す。戻したターンの録音ウィジェット
    値と自動再生済みフラグを消すので、そのターンは録音し直せてお客様セリフも再生し直す。
    戻す録音が無ければ False。
    """
    nav = st.session_state.get("rp_nav") or []
    if not nav:
        return False
    e = nav.pop()
    st.session_state["rp_nav"] = nav
    for lst_key in ("rp_audio", "rp_lines", "rp_hint_used"):
        lst = st.session_state.get(lst_key)
        if isinstance(lst, list) and lst:
            lst.pop()
    processed = st.session_state.get("rp_processed")
    if isinstance(processed, list) and e.get("rec_key") in processed:
        processed.remove(e["rec_key"])
    # 録音ウィジェットの値を消して、そのターンをまっさらに録り直せるようにする
    st.session_state.pop(e.get("rec_key"), None)
    # 自動再生済みフラグを外し、戻ったターンでお客様セリフを再度読み上げる
    st.session_state.pop(f"rp_spoken_{e.get('speak_key')}", None)
    # 位置を戻す（往復なら会話インデックスも）
    st.session_state["rp_step"] = int(e.get("turn", 0))
    if e.get("dkey") is not None:
        st.session_state[e["dkey"]] = int(e.get("didx", 0))
    return True


@st.cache_data(ttl=600, show_spinner=False)
def _unit_photo_bytes(key: str) -> bytes | None:
    """単元のフック写真バイト列（シート保存のbase64を復元）。取得失敗は None。"""
    try:
        return storage.get_unit_photo(key)
    except Exception:  # noqa: BLE001
        return None


def _render_unit_hook_photo(scenario: dict) -> None:
    """練習中の単元に紐づく『お客様に見せる施工事例（フック）』写真を表示する。

    未設定なら何も出さない。取得・表示失敗は静かにスキップ（アプリを落とさない）。
    """
    try:
        data = _unit_photo_bytes(storage.unit_photo_key(scenario))
        if not data:
            return
        st.caption("📸 お客様に見せる施工事例（フック）")
        st.image(data, use_container_width=True)
    except Exception:  # noqa: BLE001
        pass


def render_roleplay_tab(user: dict) -> None:
    st.markdown("##### 🎙️ 1人ロープレ（AIのお客様と対話 → その場で評価）")
    st.write(
        "相手役がいなくても、**1人でいつでも**ロープレできます。台本のお客様に対して"
        "声で応答し、最後に模範トークスクリプト基準で評価します。"
    )

    scenarios = storage.get_scenarios()
    # 開始したら（会話中は）単元などの選択を固定する
    locked = bool(st.session_state.get("rp_started"))

    # お客様タイプ（検討済み/未検討）では分けない。カテゴリ→単元だけで選ぶ
    # （どれを学べばよいか迷わせないため）。同名単元は未検討版を代表に1つへまとめる。
    pool = list(scenarios)
    # カテゴリは固定順で表示。応用①「反論対応」は feature flag で制御し、
    # フラグOFF＆非管理者には出さない（管理者はOFFでもプレビュー可）。
    obj_visible = settings.feature_visible("objection_drill", user.get("email"))
    cat_order = list(storage.SCRIPT_CATEGORY_ORDER)
    if obj_visible:
        # 「反論対応」で始まるカテゴリ（コーティング/エコカラット/ダウンライト…）をまとめて、
        # 基礎（4カテゴリ）の後・「その他」の手前に昇順で差し込む（3カテゴリを1フラグで制御）。
        obj_cats = sorted({str(s.get("group", "")) for s in pool
                           if str(s.get("group", "")).startswith("反論対応")})
        idx = cat_order.index("その他") if "その他" in cat_order else len(cat_order)
        for c in obj_cats:
            if c not in cat_order:
                cat_order.insert(idx, c)
                idx += 1
    groups: dict[str, list[dict]] = {}
    for cat in cat_order:
        g = [s for s in pool if s.get("group") == cat]
        if g:
            groups[cat] = g
    if not groups:
        st.info("学べる単元がありません。")
        return
    ccol, scol = st.columns([1, 2])
    with ccol:
        group = st.selectbox("カテゴリ", list(groups), key="rp_group", disabled=locked)
    # 管理者プレビュー時（フラグOFFなのに反論対応が見えている）は準備中と分かるよう注記
    if group.startswith("反論対応") and not settings.feature_enabled("objection_drill"):
        st.caption("🧪 準備中（管理者のみ表示）— 基礎習得後にプランナーへ開放予定の応用ドリルです。")
    with scol:
        # 同名単元は1つにまとめる（お客様タイプで分けない。未検討版があれば代表に）
        items, seen_t = [], set()
        for s in groups[group]:
            t = s.get("title")
            if t in seen_t:
                continue
            seen_t.add(t)
            rep = next((x for x in groups[group]
                        if x.get("title") == t and x.get("customer_type") == "未検討"), s)
            items.append(rep)
        titles = {s["id"]: s.get("title", s["id"]) for s in items}
        sid = st.selectbox("単元を選ぶ", options=list(titles),
                           format_func=lambda i: titles[i], key="rp_scenario", disabled=locked)
    scenario = storage.get_scenario(sid) or items[0]
    turns = _session_turns(scenario)
    lv = scenario.get("level", 1)
    st.caption(
        f"難易度：{'★' * int(lv)}{'☆' * (2 - int(lv))}　／ 全 {len(turns)} ターン"
    )
    if not storage.get_talk_script():
        st.caption("⚠️ 模範トークスクリプトが未登録です（下の管理者欄で登録すると、その型を基準に採点します）。")

    practice = st.toggle("🔰 練習モード（カンペを最初から表示）", value=False, key="rp_practice")

    audio = st.session_state.setdefault("rp_audio", [])
    used = st.session_state.setdefault("rp_hint_used", [])
    # 録音1件ごとに「どのお客様セリフへの応答か」を記録し、AI評価で音声と対応づける。
    # 往復（1ターン内で複数お客様セリフ）でも音声とセリフを1対1で揃えられる。
    lines_rec = st.session_state.setdefault("rp_lines", [])
    # 自動進行の重複防止：処理済み録音ウィジェットkeyの一覧（同じ録音で二重に進まない）と、
    # 「今の録音をやり直す」ためのナビ履歴（各録音の位置と speak_key を積む）。
    processed = st.session_state.setdefault("rp_processed", [])
    nav = st.session_state.setdefault("rp_nav", [])
    # 現在のターン番号（往復ターンは複数録音を消費するため len(audio) とは別管理）。
    turn = st.session_state.setdefault("rp_step", 0)

    # --- 開始ゲート：開始するまではお客様は喋らない（タブを開いただけでは無音） -------- #
    started = st.session_state.setdefault("rp_started", False)
    if not started:
        st.divider()
        st.info(
            "準備ができたら開始してください。**開始すると、お客様が自動で話し始めます。**"
            "あとは各ターンで声で返答するだけ（録音を止めると自動で次のセリフへ進みます）。"
        )
        if st.button("▶ ロープレを始める", type="primary", use_container_width=True):
            # rerun せず同じ実行のまま最初のターンへ。開始クリックのユーザー操作を
            # そのまま活かして、1ターン目のお客様セリフを自動再生できる。
            st.session_state["rp_started"] = True
            started = True
        if not started:
            if settings.is_admin(user.get("email")):
                _render_unit_admin()
            return

    if turn < len(turns):
        st.divider()
        # 往復サブフロー：chosen variant に dialog(2件以上) がある STEP2 は
        # お客様→営業→お客様→営業… と複数往復する。dialog が無いターンは従来どおり単発。
        dialog = turns[turn].get("dialog")
        is_dialog = isinstance(dialog, list) and len(dialog) >= 2
        if is_dialog:
            dkey = f"rp_dialog_idx_{sid}_{turn}"
            didx = st.session_state.setdefault(dkey, 0)
            didx = max(0, min(int(didx), len(dialog) - 1))  # 安全にクランプ
            customer_line = str(dialog[didx])
            rec_key = f"rp_rec_{turn}_{didx}"
            speak_key = f"{sid}_{turn}_{didx}"
            st.caption(f"ターン {turn + 1} / {len(turns)}　（会話 {didx + 1} / {len(dialog)}）")
        else:
            didx = None
            dkey = None
            customer_line = str(turns[turn].get("customer", ""))
            rec_key = f"rp_rec_{turn}"
            speak_key = f"{sid}_{turn}"
            st.caption(f"ターン {turn + 1} / {len(turns)}")

        _customer_bubble(customer_line, scenario.get("customer_type", "検討済み"))
        # お客様のセリフ：このターンに初めて来た時だけ自動再生（spoken フラグで二重再生を防ぐ）。
        # 2回目以降の実行では auto=False になり「🔊 もう一度きく」ボタンだけを残す。
        spoken_key = f"rp_spoken_{speak_key}"
        first_time = not st.session_state.get(spoken_key, False)
        _speak(customer_line, speak_key, auto=first_time)
        st.session_state[spoken_key] = True

        # 前のターンの録音ウィジェット値が残って表示に混ざらないよう、現在ターン以外の
        # 録音キーを session から消す（録音本体は rp_audio に保存済みなので消して安全。
        # この実行で描画するのは現在ターンの録音ウィジェットのみなので他キー削除は安全）。
        for _stale in [k for k in list(st.session_state.keys())
                       if isinstance(k, str) and k.startswith("rp_rec_") and k != rec_key]:
            del st.session_state[_stale]
        # マイク。録音を止める＝新しい録音が検出されたら、自動で保存して次のセリフへ進む。
        rec = st.audio_input("🎤 マイクを押して、お客様に返答してください（40秒以内が目安）",
                             key=rec_key)
        if nav and st.button("↩️ 今の録音をやり直す", key=f"rp_undo_{turn}_{didx}",
                             use_container_width=True):
            _roleplay_undo_last()
            st.rerun()

        if rec is not None and rec_key not in processed:
            audio.append(rec.getvalue())
            lines_rec.append(customer_line)
            used.append(bool(practice or st.session_state.get(f"rp_hint_{turn}")))
            processed.append(rec_key)  # この録音ウィジェットは処理済み（二重進行を防ぐ）
            nav.append({"rec_key": rec_key, "speak_key": speak_key,
                        "turn": turn, "didx": didx, "dkey": dkey})
            if is_dialog and didx + 1 < len(dialog):
                st.session_state[dkey] = didx + 1   # 同ターン内で次の往復へ
            else:
                st.session_state["rp_step"] = turn + 1  # 次のターンへ
            st.rerun()

        # --- カンペ（見ずに言えたら次のステップへ）。往復中も会話見本を参照できる ---
        hint = (turns[turn].get("hint") or "").strip()
        if hint:
            show = practice or st.checkbox("📋 カンペを見る（見ずに言えたら次のステップ）",
                                           key=f"rp_hint_{turn}")
            if show:
                # Markdown は単一改行を無視するため、行末に空白2つを足して改行を保つ
                st.markdown(
                    '<div style="background:#EEF3FF;border-left:4px solid #6C5CE7;'
                    'padding:.7rem 1rem;border-radius:8px;white-space:pre-wrap;'
                    'line-height:1.7;font-size:.93rem">' + _esc(hint) + "</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.caption("💡 まずは自分の言葉で。詰まったら上のチェックでカンペを開けます。")

        # 📸 この単元の「お客様に見せる施工事例（フック）」（設定時のみ）
        _render_unit_hook_photo(scenario)
    else:
        no_hint = sum(1 for u in used if not u)
        total_rec = len(used) or len(turns)
        st.success(f"全 {total_rec} 回 録音できました。評価に進めます。")
        st.markdown(f"**カンペなしで言えた：{no_hint} / {total_rec} 回**")
        if used and no_hint == len(used):
            st.balloons()
            st.success("🎉 カンペなしで完走！次の単元にステップアップしましょう。")
        elif no_hint:
            st.caption("💪 いい調子です。次はカンペを開く回数を減らしてみましょう。")
        # 直前の録音だけ録り直したい時のために、最後のターンへ1つ戻せる導線を残す
        if nav and st.button("↩️ 最後の録音をやり直す", key="rp_undo_done",
                             use_container_width=True):
            _roleplay_undo_last()
            st.rerun()

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        if audio and st.button("🤖 AIで評価する", type="primary", use_container_width=True):
            _start_roleplay_job(user, scenario, list(audio), list(lines_rec))
            _reset_roleplay()
            st.success("✅ 評価を開始しました。**この画面を閉じても大丈夫**です。")
            st.info("結果は「🕘 評価履歴」タブに出ます（混雑時は順番待ち）。")
    with c2:
        # 開始後はいつでも全体をやり直せる（単元を選び直したい時の抜け道も兼ねる）
        if st.button("↩️ 最初からやり直す（録音を破棄）", use_container_width=True):
            _reset_roleplay()
            st.rerun()

    if settings.is_admin(user.get("email")):
        _render_unit_admin()


def _render_unit_admin() -> None:
    """管理者向け：単元を選び『ロープレ（セリフ/カンペ/写真）』と『模範トークスクリプト』を1画面で編集。

    - ロープレのセリフ/カンペは overrides レイヤーに保存（再生成しても消えない）。
    - フック写真は単元（カテゴリ|タイトル）単位で知識シートに保存（外部フォルダ不要）。
    - 対応する模範トークスクリプト（タブ）があれば同じ画面で本文も編集できる（採点の型と連動）。
    """
    with st.expander("📝 単元を編集（模範トーク＆ロープレ）（管理者）"):
        scenarios = storage.get_scenarios()
        if not scenarios:
            st.caption("編集できる単元がありません。")
            return

        # カテゴリ → 単元（シナリオ）を選ぶ（この選択を両ペインで共有）
        cats = [c for c in storage.SCRIPT_CATEGORY_ORDER
                if any(s.get("group") == c for s in scenarios)]
        extra = sorted({s.get("group", "") for s in scenarios
                        if s.get("group") and s.get("group") not in cats})
        cats = cats + extra
        if not cats:
            st.caption("カテゴリが設定された単元がありません。")
            return
        ccol, ucol = st.columns([1, 2])
        with ccol:
            cat = st.selectbox("カテゴリ", cats, key="ua_cat")
        # お客様タイプで分けず、同名単元は未検討版を代表に1つへまとめる（ロープレ表示と一致）
        all_in_cat = [s for s in scenarios if s.get("group") == cat]
        pool, seen_t = [], set()
        for s in all_in_cat:
            t = s.get("title")
            if t in seen_t:
                continue
            seen_t.add(t)
            rep = next((x for x in all_in_cat
                        if x.get("title") == t and x.get("customer_type") == "未検討"), s)
            pool.append(rep)
        with ucol:
            labels = {s["id"]: s.get("title", s["id"]) for s in pool}
            sid = st.selectbox("単元を選ぶ", options=list(labels),
                               format_func=lambda i: labels[i], key="ua_scenario")
        scenario = storage.get_scenario(sid) or (pool[0] if pool else None)
        if not scenario:
            return
        raw_turns = storage.scenario_turns(scenario)

        tab_ov, tab_script = st.tabs(
            ["🎭 ロープレ（セリフ・カンペ・写真）", "📝 模範トークスクリプト（採点の型）"])

        # ---------- ロープレ編集（overrides ＋ フック写真）----------
        with tab_ov:
            if not raw_turns:
                st.caption("この単元にはターンがありません。")
            else:
                st.markdown("**📸 お客様に見せる施工事例（フック）— この単元に1枚**")
                pkey = storage.unit_photo_key(scenario)
                try:
                    cur = storage.get_unit_photo(pkey)
                except Exception:  # noqa: BLE001
                    cur = None
                if cur:
                    st.image(cur, width=260, caption="現在のフック写真")
                    if st.button("🗑️ 写真を削除", key=f"ua_photo_del_{sid}"):
                        storage.delete_unit_photo(pkey)
                        _unit_photo_bytes.clear()
                        st.success("写真を削除しました。")
                        st.rerun()
                up = st.file_uploader("フック写真を設定/差し替え（PNG/JPG）",
                                      type=["png", "jpg", "jpeg"], key=f"ua_photo_up_{sid}")
                if up is not None and st.button("📸 この写真を保存", key=f"ua_photo_save_{sid}"):
                    if storage.set_unit_photo(pkey, up.getvalue()):
                        _unit_photo_bytes.clear()
                        st.success("フック写真を保存しました（自動で縮小して保存）。")
                        st.rerun()
                    else:
                        st.warning(
                            "写真を保存できませんでした（対応していない画像形式の可能性）。"
                            "別の PNG / JPG でお試しください。"
                        )

                st.divider()
                n = len(raw_turns)
                ti = st.selectbox("ターン", options=list(range(n)),
                                  format_func=lambda i: f"ターン {i + 1} / {n}",
                                  key=f"ua_turn_{sid}")
                sc_ov = storage.get_scenario_overrides().get(sid, {}).get(str(ti), {})
                cust_default = sc_ov.get("customer") or raw_turns[ti].get("customer", "")
                hint_default = sc_ov.get("hint") or raw_turns[ti].get("hint", "")
                cust = st.text_area("① お客様セリフ", value=cust_default, height=110,
                                    key=f"ua_cust_{sid}_{ti}")
                hint = st.text_area("② カンペ（進め方・言い回し）", value=hint_default, height=180,
                                    key=f"ua_hint_{sid}_{ti}")
                st.caption("※空にして保存すると、そのターンは元の台本（自動生成）に戻ります。")
                if st.button("💾 このターンを保存", key=f"ua_save_{sid}_{ti}",
                             use_container_width=True):
                    storage.update_scenario_turn_override(sid, ti, customer=cust, hint=hint)
                    st.success(f"ターン {ti + 1} を保存しました。")
                    st.rerun()

                st.markdown("**プレビュー（実際のロープレ表示）**")
                applied = storage.persona_flavored_turns(scenario)
                if ti < len(applied):
                    _customer_bubble(applied[ti].get("customer", ""),
                                     scenario.get("customer_type", "検討済み"))
                    prev_hint = (applied[ti].get("hint") or "").strip()
                    if prev_hint:
                        st.markdown(
                            '<div style="background:#EEF3FF;border-left:4px solid #6C5CE7;'
                            'padding:.7rem 1rem;border-radius:8px;white-space:pre-wrap;'
                            'line-height:1.7;font-size:.9rem">' + _esc(prev_hint) + "</div>",
                            unsafe_allow_html=True,
                        )
                _render_unit_hook_photo(scenario)

        # ---------- 模範トークスクリプト編集（対応タブがあれば）----------
        with tab_script:
            items = storage.get_talk_script_items()
            same = sorted({i["tab"] for i in items
                           if storage.script_category(i["tab"]) == cat})
            if not same:
                st.caption(
                    "この単元（カテゴリ）に対応する模範トークスクリプトはありません。"
                    "手作り単元（ラポール・商談の導入など）は、左の🎭ロープレ側のカンペで管理します。"
                )
            else:
                title = scenario.get("title", "")
                auto = (next((t for t in same if t == title), None)
                        or next((t for t in same if title and (title in t or t in title)), None)
                        or same[0])
                st.caption(
                    "この単元の🎯模範トーク（採点の型）。ロープレのカンペと合わせて更新すると"
                    "『模範トーク視点』の採点と揃います。"
                )
                tab = st.selectbox("対応する単元（タブ）", same,
                                   index=same.index(auto), key=f"ua_sc_tab_{sid}")
                target = next((i for i in items if i.get("tab") == tab), None)
                if target:
                    body = st.text_area(
                        f"「{tab}」の内容（{len(target.get('body', '')):,}字）",
                        value=target.get("body", ""), height=300, key=f"ua_sc_body_{tab}")
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("💾 この単元を更新", key=f"ua_sc_save_{tab}",
                                     use_container_width=True):
                            if storage.update_talk_script_item(tab, body):
                                st.success(f"「{tab}」を更新しました。")
                                st.rerun()
                            else:
                                st.error("更新できませんでした。")
                    with c2:
                        if st.button("🤖 AIで整文提案", key=f"ua_sc_ai_{tab}",
                                     use_container_width=True):
                            with st.spinner("営業目線で整文しています…"):
                                try:
                                    st.session_state[f"ua_sc_prop_{tab}"] = \
                                        gemini_analyzer.refine_talk_script(body)
                                except Exception as e:  # noqa: BLE001
                                    st.session_state[f"ua_sc_prop_{tab}"] = ""
                                    st.error(f"整文に失敗しました：{_friendly_gemini_error(e)}")
                            st.rerun()

                    proposal = st.session_state.get(f"ua_sc_prop_{tab}")
                    if proposal:
                        st.markdown("**🤖 AI整文案（プレビュー）** — 内容はそのまま、言い回しを整えました")
                        col_o, col_n = st.columns(2)
                        with col_o:
                            st.caption(f"現在（{len(body):,}字）")
                            st.text(body[:1500] + ("…" if len(body) > 1500 else ""))
                        with col_n:
                            st.caption(f"AI整文案（{len(proposal):,}字）")
                            st.text(proposal[:1500] + ("…" if len(proposal) > 1500 else ""))
                        a1, a2 = st.columns(2)
                        with a1:
                            if st.button("✅ この案で更新する", key=f"ua_sc_apply_{tab}",
                                         type="primary", use_container_width=True):
                                if storage.update_talk_script_item(tab, proposal):
                                    st.session_state.pop(f"ua_sc_prop_{tab}", None)
                                    st.success(f"「{tab}」をAI整文案で更新しました。")
                                    st.rerun()
                        with a2:
                            if st.button("✖️ 却下する", key=f"ua_sc_reject_{tab}",
                                         use_container_width=True):
                                st.session_state.pop(f"ua_sc_prop_{tab}", None)
                                st.rerun()


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

    # ① 整備済みの社内ナレッジ資料（base=資料 / faq / meetings=議事録の実践知）
    base = storage.get_knowledge_doc("base")
    faq = storage.get_knowledge_doc("faq")
    meet = storage.get_knowledge_doc("meetings")
    st.divider()
    st.markdown("**📚 社内ナレッジ資料（商品・料金・サービス・FAQ・議事録）**")
    if base or faq or meet:
        st.caption(
            f"取り込み済み：資料 約{len(base):,}字 ／ FAQ 約{len(faq):,}字 ／ "
            f"議事録の実践知 約{len(meet):,}字。毎回の評価で AI がこれらを前提に判定します。"
        )
        with st.expander("資料の中身を確認する"):
            if base:
                st.text(base[:2500] + ("\n…（以下省略）" if len(base) > 2500 else ""))
            if meet:
                st.markdown("**— 議事録から学んだ実践知（抜粋）—**")
                st.text(meet[:2500] + ("\n…（以下省略）" if len(meet) > 2500 else ""))
    else:
        st.caption("まだ取り込まれていません。下のボタンでドライブの資料フォルダから取り込めます（管理者）。")

    if settings.is_admin(user.get("email")):
        _render_knowledge_doc_admin(user, has_doc=bool(base))
        _render_meeting_admin(user)

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
        _render_knowledge_items_admin(items)


_CAT_KEYS = ["product", "rule", "technique"]
_CAT_DISPLAY = {"product": "🏠 商品知識", "rule": "📏 社内ルール", "technique": "🗣️ トーク技術"}


def _render_knowledge_items_admin(items: list[dict]) -> None:
    """管理者向け：自動蓄積した知識を手入力で修正・削除・追加する。"""
    with st.expander("✏️ 知識を手入力で修正・追加（管理者）"):
        st.caption("AIが商談から抽出した知識を、人の手で正確に直せます（内容が混ざった項目の修正など）。")

        # 既存項目を選んで修正・削除
        if items:
            labels = {
                i: f"[{_CAT_DISPLAY.get(it.get('category',''), 'その他')[:2]}] {it.get('point','')[:50]}"
                for i, it in enumerate(items)
            }
            sel = st.selectbox(
                "修正する項目を選ぶ", options=list(labels), format_func=lambda i: labels[i],
                key="ki_sel",
            )
            target = items[sel]
            cat = st.selectbox(
                "カテゴリ", _CAT_KEYS, index=_CAT_KEYS.index(target.get("category"))
                if target.get("category") in _CAT_KEYS else 0,
                format_func=lambda k: _CAT_DISPLAY[k], key="ki_cat",
            )
            text = st.text_area("内容", value=target.get("point", ""), key="ki_text", height=120)
            c1, c2 = st.columns(2)
            with c1:
                if st.button("💾 この項目を更新", key="ki_update", use_container_width=True):
                    if storage.update_knowledge_item(target.get("point", ""), cat, text):
                        st.success("更新しました。")
                        st.rerun()
                    else:
                        st.error("更新できませんでした（内容が空か、項目が見つかりません）。")
            with c2:
                if st.button("🗑️ この項目を削除", key="ki_delete", use_container_width=True):
                    if storage.delete_knowledge_item(target.get("point", "")):
                        st.success("削除しました。")
                        st.rerun()

        # 新規に手入力で追加
        st.markdown("**＋ 新しい知識を追加**")
        ncat = st.selectbox("カテゴリ", _CAT_KEYS, format_func=lambda k: _CAT_DISPLAY[k], key="ki_ncat")
        ntext = st.text_area("内容", key="ki_ntext", height=80, placeholder="例：水廻りコーティングの正式名称は…")
        if st.button("➕ 追加する", key="ki_add"):
            if storage.add_knowledge_item(ncat, ntext):
                st.success("追加しました。")
                st.rerun()
            else:
                st.error("追加できませんでした（空、または既に同じ内容があります）。")

        st.divider()
        if items and st.button("🗑️ 蓄積した知識をすべて消去", key="clear_knowledge"):
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


# 議事録取り込みジョブの状態（背景スレッドと共有。st.* は使わない）。
_MEETING_JOB = {"running": False, "result": None}


def _meeting_worker(limit: int) -> None:
    from services import meeting_extractor

    try:
        _MEETING_JOB["result"] = meeting_extractor.run_extraction(limit=limit)
    except Exception as exc:  # noqa: BLE001
        _MEETING_JOB["result"] = {"error": str(exc)}
    finally:
        _MEETING_JOB["running"] = False


def _render_meeting_admin(user: dict) -> None:
    """管理者向け：商談議事録から実践ナレッジを増分取り込みする。"""
    from services import meeting_extractor

    with st.expander("📝 商談議事録から学習（増分取り込み・管理者）"):
        st.caption(
            "商談議事録フォルダから、新規分だけをAIで要約抽出してナレッジに追加します"
            "（個人情報は除外）。無料枠を守るため1回 最大30件ずつ・順番に処理します。"
        )
        processed_docs = len(storage.get_processed_meeting_ids())
        insights = storage.count_meeting_insights()
        st.caption(f"処理済み議事録：{processed_docs} 件 ／ 抽出した実践知：{insights} 件")

        if not meeting_extractor.configured():
            st.warning(
                "未設定です。議事録フォルダを知識SA（共有用アカウント）に「閲覧者」で共有し、"
                "KNOWLEDGE_SA と GEMINI_API_KEY が設定されている必要があります。"
            )
            return

        if _MEETING_JOB["running"]:
            st.info("⏳ 取り込み中です（裏で処理）。1〜数分後にこのページを更新してください。")
        else:
            res = _MEETING_JOB.get("result")
            if res:
                if res.get("error"):
                    st.error(f"取り込みエラー：{res['error'][:200]}")
                else:
                    msg = (f"取り込み完了：{res['processed']}件処理／新知見 {res['added']}件／"
                           f"展開 {res['distilled']}件／残り 約{res['remaining']}件")
                    if res.get("quota"):
                        st.warning(msg + "\n\n⚠️ 無料枠の上限に達したため途中で止まりました。時間をおいて再度押すと続きから処理します。")
                    else:
                        st.success(msg)
            if st.button("📝 新規議事録を取り込む（最大30件）", key="meet_import"):
                _MEETING_JOB["running"] = True
                _MEETING_JOB["result"] = None
                threading.Thread(target=_meeting_worker, args=(30,), daemon=True).start()
                st.rerun()
            if insights and st.button("🗑️ 議事録の学習をリセット", key="meet_clear"):
                storage.clear_meeting_insights()
                st.success("議事録の学習データを消去しました。")
                st.rerun()


def render_app(user: dict) -> None:
    # LTS共通の利用ログに「起動」を1セッション1回だけ記録（失敗しても本体は止めない）
    if not st.session_state.get("_usage_logged"):
        usage_log.log("open", user_email=user.get("email", ""), source="streamlit")
        st.session_state["_usage_logged"] = True

    components.sidebar(user)
    components.hero(compact=True)

    evaluate, roleplay, reference, knowledge, history, about = st.tabs(
        ["🎥 商談を評価する", "🎙️ 1人ロープレ", "⭐ 模範トーク",
         "🧠 弊社ナレッジ", "🕘 評価履歴", "📊 評価項目について"]
    )
    with evaluate:
        render_evaluate_tab(user)
    with roleplay:
        render_roleplay_tab(user)
    with reference:
        render_reference_tab(user)
    with knowledge:
        render_knowledge_tab(user)
    with history:
        render_history_tab(user)
    with about:
        st.markdown("##### KNOTE が見る 5 つの視点")
        components.criteria_overview()


def main() -> None:
    user = resolve_user()
    if user is None:
        render_login()
    else:
        render_app(user)


if __name__ == "__main__":
    main()
