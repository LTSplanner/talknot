"""相棒キャラクターのドット絵（16×16・2コマ）を組み立てる（純ロジック・外部I/Oなし）。

絵文字だと他のアプリと同じ顔になってしまうので、KNOTE 専用のキャラクターを
コードで描いている。ドット絵なので画像ファイルを持たずに済み、色や姿を
あとから調整してもデプロイだけで反映される。

- 1マス = 1ドット。`sprite()` は 16 行 × 16 文字の文字列を返し、文字が色番号
  （"." は透明）。実際の色は `PALETTES` を引く。
- 2コマ目は1ドット沈む／跳ねる。カクカクした昔のゲームらしい動きになる。
"""
from __future__ import annotations

GRID = 16

# 種族ごとの色。"1"=本体 "2"=影・模様 "3"=差し色 "4"=目・輪郭 "5"=白
PALETTES: dict[str, dict[str, str]] = {
    "tori": {"1": "#F7D774", "2": "#E0AE3C", "3": "#F08A3C", "4": "#3A2E20", "5": "#FFF7E2"},
    "neko": {"1": "#C9A98C", "2": "#9A7A5C", "3": "#F2A0A8", "4": "#33281F", "5": "#FFFFFF"},
    "hana": {"1": "#6FBF73", "2": "#4A8F52", "3": "#F2799F", "4": "#2E4A32",
             "5": "#FFF0C2", "6": "#9A7247"},
    "umi":  {"1": "#5FB6D9", "2": "#3C8CB5", "3": "#F2C14E", "4": "#22414F", "5": "#EAF7FF"},
    "ryu":  {"1": "#8FD16E", "2": "#3F7A38", "3": "#F2643C", "4": "#2B3A22", "5": "#FFE9A8"},
    "hoshi": {"1": "#F7E27A", "2": "#D9B84A", "3": "#B9A8F2", "4": "#3B3357", "5": "#FFFDF0"},
}


def _canvas() -> list[list[str]]:
    return [["." for _ in range(GRID)] for _ in range(GRID)]


def _px(cv, x, y, ch) -> None:
    if 0 <= x < GRID and 0 <= y < GRID:
        cv[y][x] = ch


def _disc(cv, cx, cy, rx, ry, ch) -> None:
    """楕円で塗る（ドット絵なので中心・半径は0.5刻みで使う）。"""
    for y in range(GRID):
        for x in range(GRID):
            if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0:
                cv[y][x] = ch


def _rect(cv, x0, y0, x1, y1, ch) -> None:
    for y in range(int(y0), int(y1) + 1):
        for x in range(int(x0), int(x1) + 1):
            _px(cv, x, y, ch)


def _eyes(cv, x_left, x_right, y, ch="4") -> None:
    _px(cv, x_left, y, ch)
    _px(cv, x_right, y, ch)


def _poly(cv, points, ch) -> None:
    """多角形を塗る（星などの角ばった形に使う）。"""
    for y in range(GRID):
        for x in range(GRID):
            inside = False
            px, py = x + 0.5, y + 0.5
            j = len(points) - 1
            for i, (xi, yi) in enumerate(points):
                xj, yj = points[j]
                if (yi > py) != (yj > py) and \
                        px < (xj - xi) * (py - yi) / (yj - yi + 1e-9) + xi:
                    inside = not inside
                j = i
            if inside:
                cv[y][x] = ch


def _shade(cv, ch_from="1", ch_to="2") -> None:
    """本体の下ぶちだけを暗くする。全体に模様を敷くと絵が粗く見えるため。"""
    for x in range(GRID):
        for y in range(GRID - 1, 0, -1):
            if cv[y][x] == ch_from:
                cv[y][x] = ch_to
                break


# --- 種族ごとの姿 ------------------------------------------------------------ #

def _egg(cv, speckle="2") -> None:
    """たまご・たね・いし。どの種族も1段階目はここから始まる。"""
    _disc(cv, 7.5, 9.5, 4.0, 5.0, "1")
    for x, y in ((6, 7), (9, 9), (7, 12), (10, 12)):
        _px(cv, x, y, speckle)


def _tori(cv, stage: int) -> None:
    if stage <= 1:
        _egg(cv, "2")
        return
    grow = stage - 2                       # 0〜6
    body_r = 3.0 + grow * 0.35
    cy = 10.0
    _disc(cv, 7.5, cy, body_r, body_r * 0.95, "1")
    head_r = 2.2 + grow * 0.18
    head_y = cy - body_r - head_r + 1.6
    _disc(cv, 7.5, head_y, head_r, head_r, "1")
    _eyes(cv, int(7.5 - head_r * 0.55), int(7.5 + head_r * 0.55), int(head_y))
    # くちばし
    _px(cv, 7, int(head_y) + 1, "3")
    _px(cv, 8, int(head_y) + 1, "3")
    if stage >= 4:                          # 翼
        _rect(cv, 2, cy - 1, 4, cy + 1, "2")
        _rect(cv, 11, cy - 1, 13, cy + 1, "2")
    if stage >= 6:                          # 尾羽
        _rect(cv, 12, cy + 2, 14, cy + 3, "3")
    if stage >= 8:                          # 冠羽
        _px(cv, 7, int(head_y - head_r), "3")
        _px(cv, 8, int(head_y - head_r) - 1, "3")
    _rect(cv, 6, int(cy + body_r), 6, int(cy + body_r) + 1, "3")
    _rect(cv, 9, int(cy + body_r), 9, int(cy + body_r) + 1, "3")


def _neko(cv, stage: int) -> None:
    if stage <= 1:                          # あしあと（肉球）
        _disc(cv, 7.5, 10.5, 2.8, 2.2, "1")
        for x in (4, 6, 9, 11):
            _px(cv, x, 6, "1")
            _px(cv, x, 7, "1")
        return
    grow = stage - 2                        # 0〜6
    head_r = 3.0 + grow * 0.12
    head_y = 6.0
    body_ry = 2.4 + grow * 0.26
    body_cy = 12.5
    _disc(cv, 7.5, body_cy, 3.0 + grow * 0.3, body_ry, "1")   # 体
    _rect(cv, 6, 8, 9, 12, "1")                               # 首（頭と体をつなぐ）
    _disc(cv, 7.5, head_y, head_r, head_r * 0.88, "1")        # 頭（体より大きく）
    for dx in (-1, 1):                                        # 三角の耳
        bx = 7.5 + dx * (head_r - 0.6)
        _poly(cv, [(bx - 1.4, head_y - head_r * 0.5),
                   (bx + 1.4, head_y - head_r * 0.5),
                   (bx + dx * 0.6, head_y - head_r - 0.9)], "1")
    _eyes(cv, 6, 9, 6)
    _px(cv, 7, 7, "3")                      # 鼻
    _px(cv, 8, 7, "3")
    if stage >= 3:                          # しっぽ（立ち上がる）
        _px(cv, 11, 13, "2")
        _px(cv, 12, 12, "2")
        _px(cv, 12, 11, "2")
        _px(cv, 12, 10, "2")
    if stage >= 5:                          # ひげ
        for x, dx in ((3, -1), (12, 1)):
            _px(cv, x, 7, "2")
            _px(cv, x + dx, 6, "2")
    if stage >= 6:                          # 額の縞
        _px(cv, 6, 4, "2")
        _px(cv, 9, 4, "2")
    if stage >= 8:                          # たてがみ（頭のふちを囲む）
        for x in range(GRID):
            for y in range(GRID):
                if cv[y][x] == "." and _neighbors_head(cv, x, y, head_y, head_r):
                    cv[y][x] = "3"


def _neighbors_head(cv, x, y, head_y, head_r) -> bool:
    """頭のすぐ外側か（たてがみを頭の輪郭に沿わせる）。"""
    if abs(y - head_y) > head_r + 1.6 or abs(x - 7.5) > head_r + 1.6:
        return False
    return any(0 <= y + dy < GRID and 0 <= x + dx < GRID and cv[y + dy][x + dx] == "1"
               and abs((y + dy) - head_y) <= head_r
               for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))


def _hana(cv, stage: int) -> None:
    _rect(cv, 4, 14, 11, 15, "6")           # 土（どの段階にもある）
    if stage <= 1:                          # たね
        _disc(cv, 7.5, 12.5, 1.6, 1.3, "2")
        return
    grow = stage - 2                        # 0〜6
    top = int(max(3, 12 - grow * 1.5))
    _rect(cv, 7, top, 7, 13, "1")           # 茎（1ドット）
    if stage >= 3:                          # 葉
        _disc(cv, 4.5, top + 3.0, 2.0, 1.1, "1")
        _px(cv, 6, top + 3, "2")
    if stage >= 4:
        _disc(cv, 10.5, top + 4.5, 2.0, 1.1, "1")
        _px(cv, 9, top + 4, "2")
    if stage == 4:                          # つぼみ
        _disc(cv, 7.5, top - 1.0, 1.6, 2.0, "3")
        return
    if stage >= 5:                          # 花（花びら5枚）
        r = 1.3 + (stage - 5) * 0.18
        import math

        for i in range(5):
            a = -math.pi / 2 + i * 2 * math.pi / 5
            _disc(cv, 7.5 + math.cos(a) * (r + 0.9), top - 1.0 + math.sin(a) * (r + 0.9),
                  r, r, "3")
        _disc(cv, 7.5, top - 1.0, r * 0.8, r * 0.8, "5")
    if stage >= 6:                          # 脇の小さな花
        _disc(cv, 3.0, top + 1.0, 1.2, 1.2, "3")
        _disc(cv, 12.0, top + 2.0, 1.2, 1.2, "3")
    if stage >= 7:                          # 幹が太くなる
        _rect(cv, 6, 11, 8, 13, "2")


def _umi(cv, stage: int) -> None:
    if stage <= 1:                          # あぶく（輪郭だけの泡）
        _disc(cv, 7.5, 8.5, 3.2, 3.2, "1")
        _disc(cv, 7.5, 8.5, 2.2, 2.2, ".")
        _px(cv, 6, 7, "5")
        _px(cv, 11, 4, "1")
        _px(cv, 4, 12, "1")
        return
    grow = stage - 2
    rx = 3.2 + grow * 0.55
    ry = 2.2 + grow * 0.35
    _disc(cv, 7.0, 8.5, rx, ry, "1")
    tail_x = int(7.0 + rx)
    _rect(cv, tail_x, 7, min(GRID - 1, tail_x + 2), 10, "2")   # 尾びれ
    _px(cv, int(7.0 - rx * 0.5), 8, "4")                        # 目
    if stage >= 4:                                              # 背びれ
        _rect(cv, 6, int(8.5 - ry) - 1, 8, int(8.5 - ry), "2")
    if stage >= 6:                                              # 模様
        for x in range(5, 10, 2):
            _px(cv, x, 10, "3")
    if stage >= 8:                                              # 潮吹き
        _px(cv, 5, 3, "5")
        _px(cv, 5, 2, "5")
        _px(cv, 6, 1, "5")


def _ryu(cv, stage: int) -> None:
    if stage <= 1:                          # いし
        _disc(cv, 7.5, 10.5, 4.0, 3.2, "2")
        return
    grow = stage - 2                        # 0〜6
    body_r = 2.4 + grow * 0.30
    cy = 11.0
    _disc(cv, 6.8, cy, body_r * 1.15, body_r, "1")            # 体
    head_y = 5.5
    _disc(cv, 6.5, head_y, 2.6 + grow * 0.12, 2.2 + grow * 0.1, "1")   # 頭
    _rect(cv, 8, head_y, 10, head_y + 1, "1")                 # 鼻づら（前に出す）
    _px(cv, 11, int(head_y) + 1, "1")
    _px(cv, 6, int(head_y) - 1, "4")                          # 目
    for dx, top in ((-1, 2), (1, 2)):                         # 角
        _poly(cv, [(6.5 + dx * 1.6, head_y - 1.8),
                   (6.5 + dx * 2.8, head_y - 1.8),
                   (6.5 + dx * 2.2, top)], "5")
    _rect(cv, 5, int(head_y) + 2, 7, int(cy - body_r), "1")   # 首
    if stage >= 4:                                            # 翼（三角・体より濃い色）
        _poly(cv, [(4.5, cy - 2), (0.0, cy - 6), (0.5, cy + 2)], "2")
        _poly(cv, [(9.0, cy - 2), (15.0, cy - 6), (14.5, cy + 2)], "2")
    if stage >= 5:                                            # 炎
        _px(cv, 12, int(head_y) + 2, "3")
        _px(cv, 13, int(head_y) + 3, "3")
    if stage >= 6:                                            # 背びれ
        for y in range(int(cy - body_r), int(cy) + 1, 2):
            _px(cv, 2, y, "3")
    if stage >= 8:
        for x in range(2, 15, 4):
            _px(cv, x, 0, "5")
    _px(cv, int(6.8 + body_r * 1.15), int(cy) + 1, "2")       # しっぽ
    _px(cv, min(GRID - 1, int(6.8 + body_r * 1.15) + 1), int(cy) + 2, "2")


def _star_points(cx, cy, outer, inner):
    """5つの角を持つ星の頂点（上向き）。"""
    import math

    pts = []
    for i in range(10):
        r = outer if i % 2 == 0 else inner
        a = -math.pi / 2 + i * math.pi / 5
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _hoshi(cv, stage: int) -> None:
    if stage <= 1:                          # ちり（小さなきらめきが3つ）
        for cx, cy in ((7, 8), (4, 11), (11, 5)):
            _px(cv, cx, cy, "1")
            _px(cv, cx - 1, cy, "1")
            _px(cv, cx + 1, cy, "1")
            _px(cv, cx, cy - 1, "1")
            _px(cv, cx, cy + 1, "1")
        return
    if stage == 2:                          # かけら（小さな星）
        _poly(cv, _star_points(7.5, 8.5, 3.2, 1.3), "1")
        return
    if stage in (3, 4):                     # 三日月・半月
        _disc(cv, 7.5, 8.5, 4.2, 4.2, "1")
        _disc(cv, 7.5 + (2.6 if stage == 3 else 4.0), 8.5, 4.0, 4.0, ".")
        _px(cv, 6, 8, "4")
        return
    grow = stage - 5                        # 0〜3
    _poly(cv, _star_points(7.5, 8.0, 5.0 + grow * 0.6, 2.0 + grow * 0.4), "1")
    _eyes(cv, 6, 9, 8, "4")
    if stage >= 6:                          # まわりの粒
        for x in (2, 5, 11, 14):
            _px(cv, x, 2, "5")
    if stage >= 7:
        for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            _px(cv, int(7.5 + dx * 6), int(8.0 + dy * 6), "3")
    if stage >= 8:                          # 輪
        for x in range(1, 15):
            _px(cv, x, 12, "3")
        _px(cv, 0, 11, "3")
        _px(cv, 15, 11, "3")


_FORMS = {"tori": _tori, "neko": _neko, "hana": _hana,
          "umi": _umi, "ryu": _ryu, "hoshi": _hoshi}


def sprite(species_id: str, stage: int, frame: int = 0) -> list[str]:
    """16行×16文字のドット絵を返す。frame=1 は1ドット跳ねた2コマ目。"""
    cv = _canvas()
    form = _FORMS.get(species_id, _tori)
    form(cv, max(1, min(int(stage), 8)))
    _shade(cv)
    rows = ["".join(r) for r in cv]
    if frame:
        rows = _hop(rows, species_id)
    return rows


def _hop(rows: list[str], species_id: str) -> list[str]:
    """2コマ目。生き物は1ドット上へ跳ね、植物・星は下へ沈む（揺れて見える）。"""
    blank = "." * GRID
    if species_id in ("hana", "hoshi"):
        return [blank] + rows[:-1]
    return rows[1:] + [blank]


def colors(species_id: str) -> dict[str, str]:
    return PALETTES.get(species_id, PALETTES["tori"])
