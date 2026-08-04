"""称号バッジの定義（ロープレ50個＋商談50個＝計100個）。

■ 名前のつけ方
プランナーは20代前半から40代まで、女性が多い。全員に同じトーンだと誰かが
白けるので、**系統ごとに言葉の世界観を変えて**いる。どれか1つの系統には
引っかかるように、という設計：

  🌱 草花・季節   … 続けることを労う和のトーン（continuity 系）
  ☕ 暮らし・道具 … 毎日の習慣に寄り添う言葉（habit 系）
  💎 星・宝石     … 達成の高揚感。分かりやすい格上げ（achievement 系）
  🔧 職人・手仕事 … 技術が身についた実感（craft 系）

段階（tier）は同じ系統の中で 1 から順に上がる。閾値だけで判定するので、
新しい称号は下のリストに1行足せばよい（core/badges.py の指標を使う）。

■ 判定に使う指標（core.badges.compute_metrics）
  count            実施回数
  high_streak      合計20点以上（平均4.0以上）が連続した回数
  high_total       合計20点以上の累計回数
  best_total       自己ベストの合計点（25点満点）
  day_streak       連続して実施した日数
  active_days      実施した日数
  improve_streak   前回よりスコアが上がり続けた回数
  homework_done    前回の「1ポイント」をやり切った回数
  hidden_surfaced  お客様の隠れたニーズに踏み込めた回数
  value_zone_best  会話配分の価値創出ゾーン（盲点＋秘密）の自己ベスト%
  knowledge_total  商談から抽出できた弊社ナレッジの累計
  perfect_<項目>   その評価項目で満点(5)を取った回数
"""
from __future__ import annotations

from core.badges import Badge

# (閾値, 称号名, アイコン) を並べ、カテゴリ・系統ごとに Badge へ展開する。
_RoleplayFamilies: list[tuple[str, str, str, list[tuple[float, str, str]]]] = [
    # (family, metric, 条件テンプレート, [(閾値, 名前, アイコン), ...])
    ("continuity", "count", "ロープレを{n}回やり切る", [
        (1, "はじめの一歩", "🌱"),
        (3, "三日ぶんの勇気", "🍀"),
        (5, "芽が出てきた", "🌿"),
        (10, "ふた桁の努力", "🌷"),
        (20, "根を張る人", "🌳"),
        (30, "咲きはじめ", "🌸"),
        (50, "満開まであと少し", "🌺"),
        (100, "百回の花道", "🏵️"),
    ]),
    # 連続日数は土日祝で必ず途切れるので、上限は現実的な1ヶ月まで。
    ("habit", "day_streak", "{n}日つづけてロープレする", [
        (2, "きのうの続き", "☕"),
        (3, "三日坊主を超えた", "🧺"),
        (5, "平日皆勤", "🗓️"),
        (7, "一週間の habit", "🕰️"),
        (10, "十日つづいた", "🧸"),
        (14, "二週間つづいた", "🍵"),
        (21, "三週間、体が覚えた", "🪴"),
        (30, "ひと月まいにち", "🎐"),
    ]),
    # 「ロープレした日」の累計。最後の365は“一年ぶん”の重み。連続ではないので、
    # 平日だけ続けても1年半ほどで届く。長く走り続けられる軸として置いている。
    ("habit", "active_days", "{n}日ロープレした日をつくる", [
        (5, "五日ぶんの積み木", "🧱"),
        (10, "十日の手ざわり", "🧶"),
        (20, "二十日の重み", "📚"),
        (30, "ひと月ぶんの練習", "🗂️"),
        (50, "五十日の道のり", "🚶‍♀️"),
        (75, "七十五日、板についた", "🧭"),
        (100, "百日の習慣", "🏮"),
        (150, "百五十日、ゆるがない", "🕯️"),
        (200, "二百日の蓄積", "🪵"),
        (250, "二百五十日、職人の域", "🪡"),
        (300, "三百日、ここまで来た", "🌄"),
        (365, "一年つづけた人", "🎍"),
    ]),
    ("achievement", "high_streak", "平均4.0以上（20点以上）を{n}回連続で出す", [
        (2, "二連続の手応え", "✨"),
        (3, "三連続、本物です", "⭐"),
        (5, "五連続の安定感", "🌟"),
        (7, "七連続、崩れない", "💫"),
        (10, "十連続の実力", "💎"),
        (15, "十五連続の風格", "👑"),
        (20, "二十連続、殿堂入り", "🏆"),
    ]),
    ("achievement", "high_total", "平均4.0以上（20点以上）を通算{n}回出す", [
        (1, "はじめての高得点", "🎉"),
        (5, "五つ星コレクター", "🎖️"),
        (10, "十の good job", "🥈"),
        (20, "二十の good job", "🥇"),
        (30, "三十の good job", "🏅"),
        (50, "五十の good job", "🎗️"),
    ]),
    ("achievement", "best_total", "1回のロープレで合計{n}点を取る", [
        (18, "平均3.6の手応え", "📈"),
        (20, "20点の景色", "🚩"),
        (22, "22点、かなり上位", "🎯"),
        (23, "23点、あと一歩で満点", "🔥"),
        (24, "24点、ほぼ完璧", "🌠"),
        (25, "満点、パーフェクト", "💯"),
    ]),
    ("craft", "improve_streak", "前回よりスコアを{n}回つづけて上げる", [
        (2, "右肩上がりのはじまり", "📐"),
        (3, "三段跳び", "🔧"),
        (5, "五段上がった", "⚙️"),
        (7, "伸びしろの職人", "🛠️"),
    ]),
    ("craft", "homework_done", "前回の「次に直す1点」を{n}回やり切る", [
        (1, "宿題、やってきました", "📝"),
        (3, "三つの宿題を仕上げた", "✏️"),
        (5, "五つの宿題を仕上げた", "🖊️"),
        (10, "宿題を落とさない人", "📔"),
    ]),
]

# 評価項目ごとの「満点」称号（5項目 × 各1つ）。項目名は settings から引く。
# 「極める」称号は、同じ項目で満点を何回取れば認めるか。
# 1回だと初回の評価でまとめて埋まってしまい、段階を上る実感が出ない。
_PERFECT_TIMES = 3

_PERFECT_NAMES = {
    "emotion_catch": ("感情のアンテナ", "💗"),
    "background_depth": ("背景を掘る人", "🔍"),
    "additional_consideration": ("提案の広げ上手", "🎁"),
    "adaptability": ("その場の対応力", "🌀"),
    "excitement": ("ワクワクを渡す人", "🎈"),
}

_MeetingFamilies: list[tuple[str, str, str, list[tuple[float, str, str]]]] = [
    ("continuity", "count", "商談評価を{n}回積み上げる", [
        (1, "はじめての商談評価", "🌱"),
        (3, "三つの実戦", "🍀"),
        (5, "五つの実戦", "🌿"),
        (10, "十の実戦", "🌷"),
        (20, "二十の実戦", "🌳"),
        (30, "三十の実戦", "🌸"),
        (50, "五十の実戦", "🌺"),
        (100, "百戦の記録", "🏵️"),
    ]),
    ("achievement", "high_streak", "商談で平均4.0以上（20点以上）を{n}回連続で出す", [
        (2, "二連続の good", "✨"),
        (3, "三連続、流れが来た", "⭐"),
        (5, "五連続の安定感", "🌟"),
        (7, "七連続、崩れない", "💫"),
        (10, "十連続の実力", "💎"),
        (15, "十五連続、別格", "👑"),
    ]),
    ("achievement", "high_total", "商談で平均4.0以上（20点以上）を通算{n}回出す", [
        (1, "はじめての高得点商談", "🎉"),
        (5, "五つ星の商談", "🎖️"),
        (10, "十の good job", "🥈"),
        (20, "二十の good job", "🥇"),
        (30, "三十の good job", "🏅"),
        (50, "五十の good job", "🏆"),
    ]),
    ("achievement", "best_total", "1回の商談で合計{n}点を取る", [
        (18, "平均3.6の手応え", "📈"),
        (20, "20点の商談", "🚩"),
        (22, "22点、かなり上位", "🎯"),
        (23, "23点、あと一歩で満点", "🔥"),
        (24, "24点、ほぼ完璧", "🌠"),
        (25, "満点、パーフェクト商談", "💯"),
    ]),
    ("craft", "hidden_surfaced", "お客様の隠れたニーズに{n}回踏み込む", [
        (1, "本音に触れた", "👂"),
        (5, "五つの本音を拾った", "🫧"),
        (10, "十の本音を拾った", "🪞"),
        (20, "二十の本音を拾った", "🗝️"),
        (30, "本音を引き出す人", "🕊️"),
    ]),
    ("craft", "value_zone_best", "会話配分の価値創出ゾーン（盲点＋秘密）を{n}%にする", [
        (40, "既知の確認を抜けた", "🪟"),
        (50, "半分は価値の時間", "🧭"),
        (60, "提案と本音が主役", "⚖️"),
        (70, "商談の設計者", "📐"),
        (80, "会話配分の達人", "🎼"),
    ]),
    # 「ナレッジを◯件持ち帰る」は AI が自動抽出する件数で、本人の頑張りとは
    # 結びつかないため称号にしない。代わりに、伸ばし続けた・宿題を続けた という
    # 本人の努力がそのまま出る指標に置き換えている。
    ("craft", "improve_streak", "商談で前回よりスコアを{n}回つづけて上げる", [
        (2, "前回の自分を超えた", "🪜"),
        (3, "三回つづけて伸びた", "🧗‍♀️"),
        (5, "伸び続ける人", "🚀"),
    ]),
    ("craft", "homework_streak", "商談で前回の「次に直す1点」を{n}回つづけてやり切る", [
        (2, "二回つづけてやり切った", "🧷"),
        (3, "宿題が習慣になった", "🧵"),
    ]),
    ("craft", "homework_done", "商談で前回の「次に直す1点」を{n}回やり切る", [
        (1, "宿題、やってきました", "📝"),
        (3, "三つの宿題を仕上げた", "✏️"),
        (5, "五つの宿題を仕上げた", "🖊️"),
        (10, "宿題を落とさない人", "📔"),
    ]),
]


def _expand(
    families: list[tuple[str, str, str, list[tuple[float, str, str]]]], category: str
) -> list[Badge]:
    """(系統, 指標, 条件テンプレート, 段階リスト) を Badge のリストに展開する。"""
    out: list[Badge] = []
    for family, metric, template, steps in families:
        for tier, (threshold, name, icon) in enumerate(steps, start=1):
            n = int(threshold) if float(threshold).is_integer() else threshold
            out.append(Badge(
                id=f"{category}_{metric}_{n}",
                name=name,
                description=template.format(n=n),
                icon=icon,
                category=category,
                family=family,
                tier=tier,
                metric=metric,
                threshold=threshold,
            ))
    return out


def _perfect_badges(category: str, label: str) -> list[Badge]:
    """評価項目ごとの『満点を取る』称号（5項目ぶん）。"""
    from config import settings

    out: list[Badge] = []
    for tier, c in enumerate(settings.EVALUATION_CRITERIA, start=1):
        name, icon = _PERFECT_NAMES.get(c.key, (f"{c.title}の達人", "🏅"))
        out.append(Badge(
            id=f"{category}_perfect_{c.key}",
            name=name,
            description=f"{label}で「{c.title}」の満点(5)を{_PERFECT_TIMES}回取る",
            icon=icon,
            category=category,
            family="perfect",
            tier=tier,
            metric=f"perfect_{c.key}",
            threshold=_PERFECT_TIMES,
        ))
    return out


ROLEPLAY_BADGES: list[Badge] = (
    _expand(_RoleplayFamilies, "roleplay") + _perfect_badges("roleplay", "ロープレ")
)
MEETING_BADGES: list[Badge] = (
    _expand(_MeetingFamilies, "meeting") + _perfect_badges("meeting", "商談")
)
ALL_BADGES: list[Badge] = ROLEPLAY_BADGES + MEETING_BADGES

# 系統の見出し（UI のグループ表示に使う）
FAMILY_LABELS = {
    "continuity": "🌱 続ける力",
    "habit": "☕ 習慣にする",
    "achievement": "💎 高得点をとる",
    "craft": "🔧 技を磨く",
    "perfect": "🏅 項目を極める",
}
