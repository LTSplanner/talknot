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
    """評価結果を表示する：5項目スコア → 全体講評 → タイムスタンプ別 Before/After。"""
    st.markdown(f"#### 総合スコア {result.total} / {len(settings.EVALUATION_CRITERIA) * 5}")

    cols = st.columns(len(settings.EVALUATION_CRITERIA))
    for col, c in zip(cols, settings.EVALUATION_CRITERIA):
        s = result.score_for(c.key)
        score = s.score if s else 0
        with col:
            st.markdown(
                f"""
                <div class="tk-card">
                    <div class="tk-icon">{c.icon}</div>
                    <h4><span class="tk-num">{c.number}</span> {c.title}</h4>
                    {_score_badge(score)}
                    <p>{(s.comment if s else "")}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

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
            from auth import session

            session.logout()
            st.rerun()
