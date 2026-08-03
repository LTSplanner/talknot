"""KNOTE 共通 UI コンポーネント（ロゴ・ヒーロー・評価項目カードなど）。"""
from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

from config import settings
from core.models import EvaluationResult
from ui import theme

# ライフタイムサポートのロゴ（白抜き・背景透過）。濃いブランド色の面に重ねて使う。
# 元データは青地のSNS用ロゴ（assets/lts_logo_tile.jpg）で、地色を抜いて作成した。
_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "lts_logo_white.png"


@st.cache_data(show_spinner=False)
def _logo_data_uri() -> str:
    """ロゴを data URI で返す（HTML に直接埋めるため）。無ければ空文字。"""
    try:
        return "data:image/png;base64," + base64.b64encode(
            _LOGO_PATH.read_bytes()).decode("ascii")
    except OSError:
        return ""


def _logo_img(height_px: int, opacity: float = 1.0) -> str:
    """白抜きロゴの img タグ。ロゴ画像が無ければ従来の結び目マークで代替する。"""
    uri = _logo_data_uri()
    if not uri:
        return KNOT_MARK.format(size=height_px)
    return (
        f'<img src="{uri}" alt="Life time support" '
        f'style="height:{height_px}px;width:auto;display:block;flex:none;'
        f'opacity:{opacity}">'
    )


# ブランドマーク：ヒモではなく、一本の線が交差する幾何学的な「結び目」。
KNOT_MARK = (
    '<svg viewBox="0 0 100 100" width="{size}" height="{size}" aria-hidden="true" '
    'style="flex:none;display:block">'
    '<path d="M32 32 A18 18 0 1 1 50 50 A18 18 0 1 0 68 68" fill="none" '
    'stroke="currentColor" stroke-width="7" stroke-linecap="round" opacity=".95"/>'
    '<path d="M68 32 A18 18 0 1 0 50 50" fill="none" '
    'stroke="currentColor" stroke-width="7" stroke-linecap="round" opacity=".55"/>'
    "</svg>"
)


def hero(subtitle: str | None = None, compact: bool = False) -> None:
    """ヒーローヘッダー。ライフタイムサポートのロゴと製品名 KNOTE を併記する。

    社章（Life time support）が会社、KNOTE が社内ツール名という関係なので、
    ロゴを左に置き、製品名をその右に並べる co-brand の並びにしている。
    """
    tagline = (
        f'<div class="tk-tagline">{subtitle}</div>' if subtitle and not compact else ""
    )
    klass = "tk-hero compact" if compact else "tk-hero"
    logo_h = 38 if compact else 64
    st.markdown(
        f"""
        <div class="{klass}">
            <div class="tk-brand">
                {_logo_img(logo_h)}
                <span class="tk-divider"></span>
                <h1 class="tk-logo notranslate" translate="no">KNOTE</h1>
                <span class="tk-reading notranslate" translate="no">ノート</span>
            </div>
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


def _johari_meter(j) -> None:
    """会話配分（ジョハリの窓）を横帯メーターで表示する。"""
    from core.models import JohariAllocation  # noqa: F401

    st.markdown("##### 🪟 会話配分（ジョハリの窓）")
    st.caption(
        "会話時間をどこに使えたか。**開放（既知の確認）に偏らず、盲点（プロの提案）と"
        "秘密（お客様の本音の引き出し）に時間を割けているか**が商談の質を左右します。"
    )
    total = max(1, j.open_pct + j.blind_pct + j.hidden_pct + j.unknown_pct)
    segs = [
        ("開放", j.open_pct, theme.MUTED),
        ("盲点", j.blind_pct, theme.INDIGO),
        ("秘密", j.hidden_pct, theme.CORAL),
        ("未知", j.unknown_pct, theme.SUNNY),
    ]
    bar = '<div style="display:flex;height:26px;border-radius:8px;overflow:hidden;margin:.3rem 0">'
    for name, val, color in segs:
        pct = round(val / total * 100)
        if pct <= 0:
            continue
        label = f"{name} {pct}%" if pct >= 12 else ""
        bar += (
            f'<div style="width:{pct}%;background:{color};color:#fff;font-size:.72rem;'
            f'display:flex;align-items:center;justify-content:center" title="{name} {pct}%">{label}</div>'
        )
    bar += "</div>"
    st.markdown(bar, unsafe_allow_html=True)

    value = j.value_pct
    color = theme.score_color(5 if value >= 50 else 3 if value >= 30 else 2)
    st.markdown(
        f'<p style="margin:.2rem 0"><b>価値創出ゾーン（盲点＋秘密）：'
        f'<span style="color:{color}">{value}%</span></b>'
        f'<span style="color:{theme.MUTED};font-size:.8rem"> — 高いほど、既知の確認で終わらず'
        f'提案と本音の引き出しに踏み込めた商談です</span></p>',
        unsafe_allow_html=True,
    )
    if j.comment:
        st.info(j.comment)


def _customer_profile(profile) -> None:
    """お客様の攻略メモ（属性タグ・人物像・次回の攻め方）を表示する。

    見出しは呼び出し側（折りたたみのラベル）が持つため、ここでは中身だけ描く。
    """
    if not profile:
        return
    if profile.attributes:
        pills = "".join(
            f'<span style="display:inline-block;background:{theme.INDIGO}14;'
            f'color:{theme.INDIGO};border:1px solid {theme.INDIGO}33;'
            f'border-radius:999px;padding:.2rem .7rem;margin:.15rem .3rem .15rem 0;'
            f'font-size:.82rem;font-weight:600">{a}</span>'
            for a in profile.attributes
        )
        st.markdown(
            f'<div style="margin:.3rem 0 .5rem">{pills}</div>', unsafe_allow_html=True
        )
    if profile.summary:
        st.markdown(profile.summary)
    if profile.next_approach:
        st.info(f"🎯 次回の攻め方：{profile.next_approach}")


def _follow_up_card(fu) -> None:
    """前回の宿題ができていたかの答え合わせ。今回の1ポイントの上に置く。

    「前回言われたことができたか →（できたなら）次はこれ」という順に読ませることで、
    毎回バラバラの指摘ではなく積み上げとして受け取れるようにする。
    """
    if not fu or not fu.previous_headline:
        return
    color = theme.INDIGO if fu.achieved else theme.SUNNY
    stamp = f"（⏱ {fu.timestamp}）" if fu.timestamp else ""
    st.markdown(
        f"""
        <div class="tk-card" style="text-align:left;border-left:5px solid {color}">
            <div style="color:{color};font-size:.78rem;font-weight:700;
                 letter-spacing:.08em">前回の宿題</div>
            <div style="margin:.15rem 0 .3rem;font-weight:600">{fu.previous_headline}</div>
            <div style="font-size:1.02rem">{fu.icon} {fu.label}{stamp}</div>
            <p style="margin:.25rem 0 0;color:{theme.MUTED}">{fu.comment}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _one_point_card(op) -> None:
    """『次に直す1点』を結果画面の最上部に大きく出す。

    点数・会話配分・シーン別まで一度に見せると何を直せばよいか分からなくなるため、
    ここだけ読めば次の商談で試せる状態にする（PDCA の Plan を1つに絞る）。
    """
    if not op or not (op.headline or op.action):
        return

    stamp = (
        f'<span style="background:{theme.INDIGO}14;color:{theme.INDIGO};'
        f'border-radius:999px;padding:.1rem .6rem;font-size:.78rem;'
        f'font-weight:600;margin-left:.5rem">⏱ {op.timestamp}</span>'
        if op.timestamp else ""
    )
    st.markdown(
        f"""
        <div class="tk-card" style="text-align:left;border-left:5px solid {theme.CORAL};
             background:{theme.CORAL}0d">
            <div style="color:{theme.CORAL};font-size:.8rem;font-weight:700;
                 letter-spacing:.08em">NEXT ONE POINT</div>
            <h3 style="margin:.2rem 0 .4rem">{op.headline}{stamp}</h3>
            <p style="margin:0;color:{theme.MUTED}">{op.reason}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if op.action:
        st.markdown("**🗣 次回、この一言をそのまま使ってみましょう**")
        st.info(op.action)
    if op.keep:
        st.markdown(f"✅ **続けたい良かった点：** {op.keep}")


def criteria_overview() -> None:
    """5つの評価項目をカードで一覧表示し、下に 1〜5 点の見かた（ルーブリック）を添える。"""
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
    _score_rubric()


# 1〜5点の見かた（プランナー視点）。各項目は「総合スコア」1本で採点する。
# 3観点：型（基本の流れ）／本音の引き出し（自然なニーズ発掘）／受注前進。
_SCORE_RUBRIC = [
    (5, "卓越（手本）", theme.INDIGO,
     "そのまま後輩に見せられる商談。型が自然に体に入り、詰問せずお客様の本音を引き出し、"
     "重点商材まで広げて次の一歩（次アポ・見積）まで確実に前進できています。この型を再現していきましょう。"),
    (4, "良い（安定合格）", theme.INDIGO,
     "基本の流れは安定し、本音も要所で拾えて受注に前進できています。あと一歩は、拾ったニーズを"
     "重点商材へもう一段広げて見積に残すこと。ここを足すと5に届きます。"),
    (3, "標準（普通にできた）", theme.SUNNY,
     "型どおりに進められ、大きな崩れはありません。次は“聞けた”で止めず、引き出した本音を提案・"
     "見積へつなげる一言を足すと、受注前進の手応えが変わります。"),
    (2, "あと一歩", theme.CORAL,
     "流れは追えていますが、本音の引き出しか受注前進のどちらかが弱めです。まずは会話の中で"
     "お客様自身に語らせる質問を1つ増やし、次の約束を必ず取り決めるところから始めましょう。"),
    (1, "要改善", theme.CORAL,
     "説明中心で、お客様の背景や本音を掴む前に進んでしまっています。焦らず、暮らし・家族・"
     "購入経緯を自然に聞くところから。土台の“聞く型”が身につくと一気に伸びます。"),
]


def _score_rubric() -> None:
    """評価される側（プランナー）向けに、1〜5点の見かたを前向きに示す。"""
    st.markdown("##### 🎯 総合スコア 1〜5点の見かた（プランナー視点）")
    st.caption(
        "各項目は「総合スコア」1本で採点します。**型（基本の流れ）／本音の引き出し（自然な"
        "ニーズ発掘）／受注前進** の3つをバランスで見た総合評価です。**普通にできて3・平均3.5前後**が目安。"
    )
    for score, label, color, desc in _SCORE_RUBRIC:
        st.markdown(
            f"""
            <div class="tk-card" style="text-align:left;border-left:4px solid {color}">
                <b style="color:{color};font-size:1.05rem">{score}　{label}</b>
                <p style="margin:.25rem 0 0">{desc}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _scene_feedback(f, expanded: bool = False) -> None:
    """1場面の Before → After を表示する。"""
    c = settings.CRITERIA_BY_KEY.get(f.criterion_key)
    label = f"{c.icon} {c.title}" if c else f.criterion_key
    with st.expander(f"⏱ {f.timestamp}　{label}", expanded=expanded):
        if f.emotion_note:
            st.caption(f"💗 お客様の感情の動き：{f.emotion_note}")
        if f.customer_line:
            st.caption(f"🗣 お客様の発言：「{f.customer_line}」")
        col_b, col_a = st.columns(2)
        with col_b:
            st.markdown("**Before（実際の営業トーク）**")
            if f.before:
                st.warning(f.before)
            else:
                st.caption("この場面の営業トークは特定できませんでした"
                           "（お客様の発言との取り違えを検出したため非表示）")
        with col_a:
            st.markdown("**After（こう言えたら）**")
            st.info(f.after)


def evaluation_result(result: EvaluationResult) -> None:
    """評価結果を表示する。

    読む順番は「前回の宿題ができたか → 今回の1点 → その根拠になった場面」。
    点数・会話配分・隠れたニーズ・攻略メモは畳んでおき、見たい人だけが開く。
    見る項目が多いと何を改善すべきか分からなくなるため、既定では絞って見せる。
    """
    _follow_up_card(result.follow_up)

    op = result.one_point
    if op:
        _one_point_card(op)
    elif result.summary:
        # 1ポイントが無い過去データは、従来どおり全体講評を先頭に出す。
        st.markdown("##### 全体の振り返り")
        st.success(result.summary)

    if result.feedback:
        st.markdown("##### 🎬 決定的だった場面（Before → After）")
        st.caption("この商談の分かれ目になった場面だけを抜き出しています。")
        for i, f in enumerate(result.feedback):
            _scene_feedback(f, expanded=(i == 0))

    full = len(settings.EVALUATION_CRITERIA) * 5
    with st.expander(f"📊 スコアの詳細（{result.overall_total} / {full}）と会話配分"):
        # 総合スコア1本（旧2軸データは sales_score を総合として表示する）。
        st.metric("🎯 総合スコア 合計", f"{result.overall_total} / {full}")

        cols = st.columns(len(settings.EVALUATION_CRITERIA))
        for col, c in zip(cols, settings.EVALUATION_CRITERIA):
            s = result.score_for(c.key)
            sales_s = s.sales_score if s else 0
            sales_cmt = s.sales_comment if s else ""
            with col:
                st.markdown(
                    f"""
                    <div class="tk-card">
                        <div class="tk-icon">{c.icon}</div>
                        <h4><span class="tk-num">{c.number}</span> {c.title}</h4>
                        {_score_badge(sales_s)}
                        <p>{sales_cmt}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        if result.johari:
            _johari_meter(result.johari)

    if result.hidden_needs:
        with st.expander(f"🔍 お客様の隠れたニーズ（{len(result.hidden_needs)}件）"):
            st.caption(
                "お客様が言葉にしていない不安・疑問を、非言語サインから読み取ったものです。"
                "✅＝営業が踏み込めた／⚠️＝表面で流した。"
            )
            for h in result.hidden_needs:
                caught = "✅ 踏み込めた" if h.surfaced else "⚠️ 取りこぼし"
                head = f"⏱ {h.timestamp}　{caught}" if h.timestamp else caught
                st.markdown(f"**{head}　— {h.inferred_need}**")
                if h.signal:
                    st.caption(f"🫧 読み取ったサイン：{h.signal}")
                if h.note:
                    (st.info if h.surfaced else st.warning)(h.note)

    if result.customer_profile:
        with st.expander("🧭 このお客様の攻略メモ（次回の活かし方）"):
            _customer_profile(result.customer_profile)

    if op and result.summary:
        with st.expander("📝 全体の振り返り"):
            st.success(result.summary)


def _badge_tile(status) -> str:
    """称号1つぶんのタイル HTML。未取得は色を抜いて進捗バーを出す。"""
    b = status.badge
    if status.earned:
        return (
            '<div class="tk-badge earned">'
            f'<div class="b-icon">{b.icon}</div>'
            f'<div class="b-name">{b.name}</div>'
            f'<div class="b-desc">{b.description}</div>'
            "</div>"
        )
    pct = round(status.progress * 100)
    # 「あと◯」が見えると次の一歩が具体的になる（0/◯ のときは出さない）
    left = (
        f'<div class="b-left">あと {status.remaining:.0f}</div>'
        if status.current > 0 else '<div class="b-left">これから</div>'
    )
    return (
        '<div class="tk-badge locked">'
        f'<div class="b-icon">{b.icon}</div>'
        f'<div class="b-name">？？？</div>'
        f'<div class="b-desc">{b.description}</div>'
        f'<div class="b-bar"><span style="width:{pct}%"></span></div>'
        f"{left}</div>"
    )


def badge_collection(statuses: list, who_label: str = "") -> None:
    """称号バッジのコレクション画面（個人ページ）。

    取得済みは色付き、未取得はグレーで条件と進捗だけ見せる。何を頑張れば
    埋まるのかが分かるように、未取得も隠さず並べる方針。
    """
    from core import badges as _badges
    from core.badge_defs import FAMILY_LABELS

    total = len(statuses)
    got = _badges.earned_count(statuses)
    st.markdown(f"#### 🏅 {who_label}称号コレクション　{got} / {total}")
    st.progress(got / total if total else 0.0)

    nxt = _badges.next_up(statuses, 3)
    if nxt:
        st.markdown("**あと少しで取れる称号**")
        cols = st.columns(len(nxt))
        for col, s in zip(cols, nxt):
            col.markdown(
                f"{s.badge.icon} **{s.badge.name}**　"
                f"<span style='color:{theme.MUTED};font-size:.85rem'>"
                f"{s.badge.description}（あと {s.remaining:.0f}）</span>",
                unsafe_allow_html=True,
            )
        st.divider()

    for category, label in (("roleplay", "🎙️ 1人ロープレ"), ("meeting", "🎥 商談")):
        in_cat = [s for s in statuses if s.badge.category == category]
        cat_got = _badges.earned_count(in_cat)
        st.markdown(f"##### {label}　{cat_got} / {len(in_cat)}")
        for family, fam_label in FAMILY_LABELS.items():
            in_fam = [s for s in in_cat if s.badge.family == family]
            if not in_fam:
                continue
            fam_got = _badges.earned_count(in_fam)
            st.caption(f"{fam_label}　{fam_got} / {len(in_fam)}")
            tiles = "".join(_badge_tile(s) for s in in_fam)
            st.markdown(f'<div class="tk-badge-grid">{tiles}</div>',
                        unsafe_allow_html=True)


def sidebar(user: dict) -> None:
    """ログイン中ユーザー情報とナビゲーションを表示するサイドバー。"""
    with st.sidebar:
        # サイドバーは白地なので、白抜きロゴはブランド色のタイルに載せて見せる。
        st.markdown(
            f'<div class="tk-brand" style="color:{theme.BRAND_DEEP}">'
            f'<span class="tk-logo-tile">{_logo_img(26)}</span>'
            '<span class="notranslate" translate="no" style="font-weight:700;'
            'font-size:1.25rem;letter-spacing:-.03em">KNOTE</span></div>',
            unsafe_allow_html=True)
        st.divider()
        st.markdown(f"**{user.get('name', 'ゲスト')}**")
        st.caption(user.get("email", ""))
        if settings.is_admin(user.get("email")):
            st.markdown("🛡️ 管理者")
        elif settings.is_viewer(user.get("email")):
            st.markdown("👁️ 閲覧専用")
        st.divider()
        if st.button("ログアウト", use_container_width=True):
            from auth import persist, session

            persist.clear()  # 保存したログインCookieも消す
            session.logout()
            st.rerun()
