"""KNOTE のビジュアルアイデンティティ（カラー・フォント・CSS）。

コンセプト：Talk（話す）＋ Knot（結び目・絆）。
配色はライフタイムサポートのコーポレートカラー（PANTONE 7451M ／
RGB 155-180-200 ＝ #9BB4C8 のダスティブルー）を軸にした、落ち着いた信頼感のトーン。

■ 色の使い分け（重要）
ブランド原色 #9BB4C8 は淡いため、**白地の文字には使えない**（コントラスト 2.15:1）。
そこで「面に敷く色」と「文字・線に使う色」を分けている：
  - BRAND      … 帯・メーター・ロゴ地など**面**に敷く（文字色には使わない）
  - BRAND_DEEP … 文字・アイコン・枠線に使う濃度（白地で 5.19:1 ＝ AA 合格）
  - BRAND_INK  … 見出し・ヒーローの濃い端（白地で 7.76:1）
差し色（ACCENT / ATTENTION / POSITIVE）も、白地・クリーム地の両方で
本文コントラスト AA（4.5:1）を満たす濃度に調整済み。色を足すときも同じ基準で選ぶこと。
"""
from __future__ import annotations

import streamlit as st

# --- コーポレートカラー（PANTONE 7451M）---
BRAND = "#9BB4C8"       # 原色：ロゴのダスティブルー。面に敷く用
BRAND_SOFT = "#C9D8E4"  # 淡い面（帯の明るい端・ホバー）
BRAND_DEEP = "#4E7189"  # 文字・線に使える濃度（白地 5.19:1）
BRAND_INK = "#35566E"   # 見出し・グラデーションの濃い端（白地 7.76:1）

# --- 差し色（ブランドのダスティブルーと調和する彩度に落としたもの）---
ACCENT = "#AE5943"      # 気づき・注目（テラコッタ。白地 4.87:1）
ATTENTION = "#8E6A2A"   # 途中・要注意（サンド。白地 4.95:1）
POSITIVE = "#3F7365"    # 達成・高評価（セージ。白地 5.45:1）

CREAM = "#FAF8F4"       # 背景（ロゴ台紙のオフホワイト）
INK = "#263238"         # 本文
MUTED = "#6B7884"       # 補助文字（白地 4.52:1）
GRADIENT = f"linear-gradient(120deg, {BRAND} 0%, {BRAND_INK} 100%)"
# 白文字を乗せる面（ヒーロー帯・ボタン）専用。淡い端を使うと白文字が読めなくなるため、
# 濃い側だけでグラデーションを作る（白文字コントラスト 5.19:1〜7.76:1）。
GRADIENT_ON_DARK = f"linear-gradient(120deg, {BRAND_DEEP} 0%, {BRAND_INK} 100%)"

# 旧名との互換（既存の呼び出しを壊さないための別名）。
# 新しく書くコードでは上のブランド名（BRAND_DEEP など）を使うこと。
INDIGO = BRAND_DEEP
CORAL = ACCENT
SUNNY = ATTENTION
TEAL = POSITIVE


def score_color(score: int) -> str:
    """1〜5 のスコアを段階的な色にマッピングする。"""
    if score >= 5:
        return POSITIVE
    if score >= 4:
        return BRAND_DEEP
    if score >= 3:
        return ATTENTION
    return ACCENT


_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Quicksand:wght@500;600;700&family=Noto+Sans+JP:wght@400;500;700&display=swap');

html, body, [class*="css"] {{
    font-family: 'Noto Sans JP', 'Quicksand', sans-serif;
    color: {INK};
}}
.stApp {{
    background:
        radial-gradient(900px 360px at 88% -8%, {BRAND}33, transparent 60%),
        radial-gradient(800px 380px at -6% 6%, {BRAND_SOFT}3d, transparent 55%),
        {CREAM};
}}

/* --- ロゴ / ヒーロー --- */
.tk-hero {{
    position: relative;
    overflow: hidden;
    background: {GRADIENT_ON_DARK};
    border-radius: 26px;
    padding: 2.6rem 2.8rem;
    color: #fff;
    box-shadow: 0 18px 46px rgba(53, 86, 110, 0.26);
    margin-bottom: 1.7rem;
}}
.tk-hero::after {{
    content: "";
    position: absolute;
    right: -1.2rem; bottom: -3.2rem;
    width: 190px; height: 190px; border-radius: 50%;
    border: 22px solid rgba(255,255,255,0.13);
    border-right-color: transparent; border-bottom-color: transparent;
    transform: rotate(-18deg);
}}
.tk-hero.compact {{ padding: 1.25rem 1.8rem; border-radius: 20px; }}
.tk-hero.compact::after {{ width: 118px; height: 118px; border-width: 14px; bottom: -2.1rem; }}
.tk-brand {{ display: flex; align-items: center; gap: 0.85rem; }}
.tk-logo {{
    font-family: 'Helvetica Neue', Arial, sans-serif;
    font-weight: 700;
    font-size: 2.9rem;
    letter-spacing: -0.035em;
    margin: 0; line-height: 1.02;
}}
.tk-reading {{
    font-size: 0.78rem; letter-spacing: 0.22em; opacity: 0.72;
    align-self: flex-end; padding-bottom: 0.5rem;
}}
.tk-hero.compact .tk-logo {{ font-size: 1.9rem; }}
.tk-hero.compact .tk-reading {{ font-size: 0.68rem; padding-bottom: 0.25rem; }}
.tk-tagline {{ font-size: 1.08rem; opacity: 0.96; margin-top: 0.5rem; font-weight: 500; }}

/* --- カード --- */
.tk-card {{
    position: relative;
    background: #fff;
    border-radius: 20px;
    padding: 1.5rem 1.4rem 1.3rem;
    box-shadow: 0 6px 22px rgba(38, 50, 56, 0.07);
    border: 1px solid rgba(78, 113, 137, 0.12);
    height: 100%;
    transition: transform .14s ease, box-shadow .2s ease;
}}
.tk-card::before {{
    content: ""; position: absolute; top: 0; left: 1.4rem; right: 1.4rem; height: 4px;
    border-radius: 0 0 6px 6px; background: {GRADIENT}; opacity: .85;
}}
.tk-card:hover {{
    transform: translateY(-4px);
    box-shadow: 0 14px 32px rgba(78, 113, 137, 0.18);
}}
.tk-card h4 {{ margin: 0.3rem 0 0.45rem; font-size: 1.02rem; font-weight: 700; }}
.tk-card p {{ margin: 0; color: {MUTED}; font-size: 0.88rem; line-height: 1.55; }}
.tk-card .tk-icon {{ font-size: 1.9rem; }}
.tk-num {{ color: {BRAND_DEEP}; font-weight: 700; }}

/* --- ボタン --- */
.stButton > button, .stLinkButton > a {{
    border-radius: 999px;
    border: none;
    padding: 0.6rem 1.5rem;
    font-weight: 700;
    background: {GRADIENT_ON_DARK};
    color: #fff !important;
    transition: transform .08s ease, box-shadow .2s ease;
}}
.stButton > button:hover, .stLinkButton > a:hover {{
    transform: translateY(-1px);
    box-shadow: 0 10px 24px rgba(78, 113, 137, 0.32);
    color: #fff !important;
}}

/* --- タブ --- */
.stTabs [data-baseweb="tab-list"] {{ gap: 0.45rem; }}
.stTabs [data-baseweb="tab"] {{
    border-radius: 999px; padding: 0.35rem 1.05rem; background: #fff;
    border: 1px solid rgba(78,113,137,.14);
}}
.stTabs [aria-selected="true"] {{
    background: {BRAND_DEEP}14; color: {BRAND_DEEP};
    border-color: {BRAND_DEEP}55;
}}

#MainMenu, footer {{ visibility: hidden; }}

/* --- スマートフォン最適化（〜640px）--- */
@media (max-width: 640px) {{
    /* 本文の左右余白を詰めて画面を広く使う */
    .block-container {{ padding: 1rem 0.9rem 3rem !important; }}

    /* ヒーローをコンパクトに */
    .tk-hero {{ padding: 1.5rem 1.4rem; border-radius: 20px; margin-bottom: 1.2rem; }}
    .tk-hero::after {{ font-size: 4rem; right: 1rem; }}
    .tk-logo {{ font-size: 2rem; }}
    .tk-hero.compact .tk-logo {{ font-size: 1.5rem; }}
    .tk-tagline {{ font-size: 0.95rem; }}

    /* カードの余白と、ホバーで浮かせる演出（タッチでは不要）を抑える */
    .tk-card {{ padding: 1.15rem 1.1rem 1rem; border-radius: 16px; }}
    .tk-card:hover {{ transform: none; }}
    .tk-card .tk-icon {{ font-size: 1.6rem; }}

    /* タブは横スクロールで全項目に届くように */
    .stTabs [data-baseweb="tab-list"] {{ overflow-x: auto; flex-wrap: nowrap; }}
    .stTabs [data-baseweb="tab"] {{ white-space: nowrap; padding: 0.3rem 0.85rem; }}

    /* タップしやすいようにボタンを大きめに */
    .stButton > button, .stLinkButton > a {{
        width: 100%; padding: 0.7rem 1.2rem; font-size: 1rem;
    }}
}}
</style>
"""


def inject_css() -> None:
    """全ページ共通の CSS を注入する。set_page_config の直後に呼ぶこと。"""
    st.markdown(_CSS, unsafe_allow_html=True)
