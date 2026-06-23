"""TalKnot 共通 UI コンポーネント（ロゴ・ヒーロー・評価項目カードなど）。"""
from __future__ import annotations

import streamlit as st

from config import settings
from core.models import EvaluationResult
from ui import theme


def hero(subtitle: str | None = None, compact: bool = False) -> None:
    """ブランドロゴ入りのヒーローヘッダー。"""
    tagline = (
        f'<div class="tk-tagline">{subtitle}</div>' if subtitle and not compact else ""
    )
    klass = "tk-hero compact" if compact else "tk-hero"
    st.markdown(
        f"""
        <div class="{klass}">
            <h1 class="tk-logo">トーク<span class="knot">🪢</span>ノット</h1>
            {tagline}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _score_badge(score: int) -> str:
    color = theme.score_color(score)
    return (
        f'<p style="font-size:1.7rem;font-weight:700;color:{color};margin:.3rem 0">'
        f'{score}<span style="font-size:.85rem;color:{theme.MUTED}"> / 5</span></p>'
    )


def _dual_axis_badge(reference_score: int, sales_score: int) -> str:
    """🎯模範視点 ／ 💼営業プロ視点 の2スコアを横並びで表示する。"""
    ref_axis = settings.AXES_BY_KEY["reference"]
    sales_axis = settings.AXES_BY_KEY["sales"]
    ref_c = theme.score_color(reference_score)
    sales_c = theme.score_color(sales_score)
    return (
        '<div style="display:flex;gap:.6rem;margin:.4rem 0">'
        f'<div style="flex:1;text-align:center;background:{ref_c}14;border-radius:12px;padding:.35rem">'
        f'<div style="font-size:.72rem;color:{theme.MUTED}">{ref_axis.icon} {ref_axis.title}</div>'
        f'<div style="font-size:1.35rem;font-weight:700;color:{ref_c}">{reference_score}'
        f'<span style="font-size:.7rem;color:{theme.MUTED}"> / 5</span></div></div>'
        f'<div style="flex:1;text-align:center;background:{sales_c}14;border-radius:12px;padding:.35rem">'
        f'<div style="font-size:.72rem;color:{theme.MUTED}">{sales_axis.icon} {sales_axis.title}</div>'
        f'<div style="font-size:1.35rem;font-weight:700;color:{sales_c}">{sales_score}'
        f'<span style="font-size:.7rem;color:{theme.MUTED}"> / 5</span></div></div>'
        '</div>'
    )


def criteria_overview() -> None:
    """5つの評価項目をカードで一覧表示する。"""
    cols = st.columns(len(settings.EVALUATION_CRITERIA))
    for col, c in zip(cols, settings.EVALUATION_CRITERIA):
        with col:
            st.markdown(
                f"""
                <div class="tk-card">
                    <div class="tk-icon">{c.icon}</div>
                    <h4><span class="tk-num">{c.number}</span> {c.title}</h4>
                    <p>{c.description}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )


def evaluation_result(result: EvaluationResult) -> None:
    """評価結果を表示する：2軸の総合 → 5項目を2軸スコア → 全体講評 → Before/After。"""
    full = len(settings.EVALUATION_CRITERIA) * 5
    ref_axis = settings.AXES_BY_KEY["reference"]
    sales_axis = settings.AXES_BY_KEY["sales"]
    c1, c2 = st.columns(2)
    with c1:
        st.metric(f"{ref_axis.icon} {ref_axis.title} 合計", f"{result.reference_total} / {full}")
    with c2:
        st.metric(f"{sales_axis.icon} {sales_axis.title} 合計", f"{result.sales_total} / {full}")

    cols = st.columns(len(settings.EVALUATION_CRITERIA))
    for col, c in zip(cols, settings.EVALUATION_CRITERIA):
        s = result.score_for(c.key)
        ref_s = s.reference_score if s else 0
        sales_s = s.sales_score if s else 0
        ref_cmt = s.reference_comment if s else ""
        sales_cmt = s.sales_comment if s else ""
        with col:
            st.markdown(
                f"""
                <div class="tk-card">
                    <div class="tk-icon">{c.icon}</div>
                    <h4><span class="tk-num">{c.number}</span> {c.title}</h4>
                    {_dual_axis_badge(ref_s, sales_s)}
                    <p><b>{sales_axis.icon}</b> {sales_cmt}</p>
                    <p style="color:{theme.MUTED};font-size:.82rem"><b>{ref_axis.icon}</b> {ref_cmt}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

    if result.hidden_needs:
        st.markdown("##### 🔍 お客様の隠れたニーズ（秘密領域）")
        st.caption(
            "お客様が言葉にしていない不安・疑問を、非言語サインから読み取ったものです。"
            "✅＝営業が踏み込めた／⚠️＝表面で流した。"
        )
        for h in result.hidden_needs:
            caught = "✅ 踏み込めた" if h.surfaced else "⚠️ 取りこぼし"
            head = f"⏱ {h.timestamp}　{caught}" if h.timestamp else caught
            with st.expander(f"{head}　— {h.inferred_need}"):
                if h.signal:
                    st.caption(f"🫧 読み取ったサイン：{h.signal}")
                st.markdown(f"**隠れたニーズ：** {h.inferred_need}")
                if h.note:
                    (st.info if h.surfaced else st.warning)(h.note)

    if result.summary:
        st.markdown("##### 全体の振り返り")
        st.success(result.summary)

    if result.feedback:
        st.markdown("##### シーン別フィードバック（Before → After）")
        for f in result.feedback:
            c = settings.CRITERIA_BY_KEY.get(f.criterion_key)
            label = f"{c.icon} {c.title}" if c else f.criterion_key
            with st.expander(f"⏱ {f.timestamp}　{label}"):
                if f.emotion_note:
                    st.caption(f"💗 お客様の感情の動き：{f.emotion_note}")
                col_b, col_a = st.columns(2)
                with col_b:
                    st.markdown("**Before（実際のトーク）**")
                    st.warning(f.before)
                with col_a:
                    st.markdown("**After（こう言えたら）**")
                    st.info(f.after)


def sidebar(user: dict) -> None:
    """ログイン中ユーザー情報とナビゲーションを表示するサイドバー。"""
    with st.sidebar:
        st.markdown("### トークノット 🪢")
        st.caption("お話が楽しくなる。お客様との絆が、結ばれる。")
        st.divider()
        st.markdown(f"**{user.get('name', 'ゲスト')}**")
        st.caption(user.get("email", ""))
        if settings.is_admin(user.get("email")):
            st.markdown("🛡️ 管理者")
        st.divider()
        if st.button("ログアウト", use_container_width=True):
            from auth import persist, session

            persist.clear()  # 保存したログインCookieも消す
            session.logout()
            st.rerun()
