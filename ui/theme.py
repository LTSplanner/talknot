"""TalKnot のビジュアルアイデンティティ（カラー・フォント・CSS）。

コンセプト：Talk（話す）＋ Knot（結び目・絆）。
ふたりの会話が結ばれていくイメージを、コーラル→インディゴのグラデーションで表現。
"""
from __future__ import annotations

import streamlit as st

# --- ブランドカラー ---
CORAL = "#FF6F61"      # 会話のあたたかさ
INDIGO = "#6C5CE7"     # 信頼・深まり
SUNNY = "#FFC36B"      # ワクワク・期待
TEAL = "#2BC4A6"       # 高評価・達成
CREAM = "#FFF9F4"      # 背景
INK = "#2D2A32"        # 文字
MUTED = "#8C8794"      # 補助文字
GRADIENT = f"linear-gradient(120deg, {CORAL} 0%, {INDIGO} 100%)"


def score_color(score: int) -> str:
    """1〜5 のスコアを段階的な色にマッピングする。"""
    if score >= 5:
        return TEAL
    if score >= 4:
        return INDIGO
    if score >= 3:
        return SUNNY
    return CORAL


_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Quicksand:wght@500;600;700&family=Noto+Sans+JP:wght@400;500;700&display=swap');

html, body, [class*="css"] {{
    font-family: 'Noto Sans JP', 'Quicksand', sans-serif;
    color: {INK};
}}
.stApp {{
    background:
        radial-gradient(900px 360px at 88% -8%, {SUNNY}22, transparent 60%),
        radial-gradient(800px 380px at -6% 6%, {CORAL}1f, transparent 55%),
        {CREAM};
}}

/* --- ロゴ / ヒーロー --- */
.tk-hero {{
    position: relative;
    overflow: hidden;
    background: {GRADIENT};
    border-radius: 26px;
    padding: 2.6rem 2.8rem;
    color: #fff;
    box-shadow: 0 18px 46px rgba(108, 92, 231, 0.28);
    margin-bottom: 1.7rem;
}}
.tk-hero::after {{
    content: "🪢";
    position: absolute;
    right: 1.6rem; bottom: -0.6rem;
    font-size: 6.5rem; opacity: 0.16;
    transform: rotate(-8deg);
}}
.tk-hero.compact {{ padding: 1.25rem 1.8rem; border-radius: 20px; }}
.tk-hero.compact::after {{ font-size: 3.6rem; bottom: -0.4rem; }}
.tk-logo {{
    font-family: 'Quicksand', sans-serif;
    font-weight: 700;
    font-size: 2.9rem;
    letter-spacing: 0.5px;
    margin: 0; line-height: 1.05;
}}
.tk-logo .knot {{ filter: drop-shadow(0 2px 6px rgba(0,0,0,.18)); }}
.tk-hero.compact .tk-logo {{ font-size: 1.9rem; }}
.tk-tagline {{ font-size: 1.08rem; opacity: 0.96; margin-top: 0.5rem; font-weight: 500; }}

/* --- カード --- */
.tk-card {{
    position: relative;
    background: #fff;
    border-radius: 20px;
    padding: 1.5rem 1.4rem 1.3rem;
    box-shadow: 0 6px 22px rgba(45, 42, 50, 0.07);
    border: 1px solid rgba(108, 92, 231, 0.08);
    height: 100%;
    transition: transform .14s ease, box-shadow .2s ease;
}}
.tk-card::before {{
    content: ""; position: absolute; top: 0; left: 1.4rem; right: 1.4rem; height: 4px;
    border-radius: 0 0 6px 6px; background: {GRADIENT}; opacity: .85;
}}
.tk-card:hover {{
    transform: translateY(-4px);
    box-shadow: 0 14px 32px rgba(108, 92, 231, 0.16);
}}
.tk-card h4 {{ margin: 0.3rem 0 0.45rem; font-size: 1.02rem; font-weight: 700; }}
.tk-card p {{ margin: 0; color: {MUTED}; font-size: 0.88rem; line-height: 1.55; }}
.tk-card .tk-icon {{ font-size: 1.9rem; }}
.tk-num {{ color: {CORAL}; font-weight: 700; }}

/* --- ボタン --- */
.stButton > button, .stLinkButton > a {{
    border-radius: 999px;
    border: none;
    padding: 0.6rem 1.5rem;
    font-weight: 700;
    background: {GRADIENT};
    color: #fff !important;
    transition: transform .08s ease, box-shadow .2s ease;
}}
.stButton > button:hover, .stLinkButton > a:hover {{
    transform: translateY(-1px);
    box-shadow: 0 10px 24px rgba(108, 92, 231, 0.32);
    color: #fff !important;
}}

/* --- タブ --- */
.stTabs [data-baseweb="tab-list"] {{ gap: 0.45rem; }}
.stTabs [data-baseweb="tab"] {{
    border-radius: 999px; padding: 0.35rem 1.05rem; background: #fff;
    border: 1px solid rgba(108,92,231,.1);
}}
.stTabs [aria-selected="true"] {{
    background: {CORAL}1a; color: {CORAL};
    border-color: {CORAL}55;
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
