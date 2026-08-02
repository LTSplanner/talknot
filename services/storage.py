"""模範トーク・評価履歴の永続化。

保存先は2系統：
- `settings.GCS_BUCKET` が設定されていれば **Google Cloud Storage**（Cloud Run 等で
  再起動しても消えないようにする本番向け）。
- 未設定ならローカルファイル（`settings.DATA_DIR`。ローカル開発・テスト向け）。

入出力インターフェースをここに集約し、呼び出し側（app.py）は保存先を意識しない。
"""
from __future__ import annotations

import datetime as _dt
import json
import time
from pathlib import Path

from config import settings
from core.models import EvaluationResult, KnowledgeItem

_JST = _dt.timezone(_dt.timedelta(hours=9))


def _now_jst_str() -> str:
    """保存時刻を JST（+9）の "YYYY-MM-DD HH:MM:SS" で返す。

    サーバ(Streamlit Cloud)のタイムゾーンは UTC のため、time.strftime だと UTC で
    記録され表示が9時間ずれる。評価履歴の表示・ナッジ/休みの日付判定はすべて JST 前提
    なので、ここで JST に固定する。
    """
    return _dt.datetime.now(_JST).strftime("%Y-%m-%d %H:%M:%S")

# 弊社ナレッジ（蓄積知識）の保存名と上限。
_KNOWLEDGE_NAME = "knowledge.json"
# 知識項目の上限。超えたら古いものから間引き、毎回の評価コストと容量を一定に保つ。
_KNOWLEDGE_MAX_ITEMS = 150
# 社内ナレッジ資料（商品・料金・サービス・FAQ の整備済みテキスト）の保存名と、
# 評価プロンプトへ載せる文字数上限（トークン暴発防止）。
# 社内資料ドキュメントは3セクションを独立保存する（再取り込みが互いに干渉しない）。
#   base     … 整備版資料（商品・料金・サービス）
#   faq      … FAQ統合シート抜粋
#   meetings … 商談議事録から抽出した実践知
_DOC_KINDS = {
    "base": ("knowledge_doc.txt", "KnowledgeDoc"),
    "faq": ("knowledge_faq.txt", "KnowledgeFAQ"),
    "meetings": ("knowledge_meetings.txt", "KnowledgeMeetings"),
    # 1人ロープレ用：模範トークスクリプト本文と、シナリオ台本(JSON)
    "script": ("talk_script.txt", "TalkScript"),
    "scenarios": ("roleplay_scenarios.json", "RoleplayScenarios"),
    # 議事録から作ったお客様ペルソナ（属性別の反応・不安・口ぐせ・断り文句）
    "persona": ("customer_persona.json", "CustomerPersona"),
    # ロープレの「進め方の切り口」コーチング（カテゴリ×属性別）
    "coaching": ("coaching_tips.json", "CoachingTips"),
    # 管理者による「お客様セリフ・カンペ」の上書きレイヤー。
    # シナリオを再生成(build script)しても、この上書きは別ドキュメントに保存されるため消えない。
    "overrides": ("scenario_overrides.json", "ScenarioOverrides"),
    # 単元（カテゴリ|タイトル）ごとの「お客様に見せるフック写真」。
    # 縮小JPEGをbase64にしてシートへ保存（save_doc が行分割で長文も安全に保存する）。
    "unit_photos": ("unit_photos.json", "UnitPhotos"),
}
_KNOWLEDGE_DOC_BUDGET = 60000   # base 上限
_FAQ_DOC_BUDGET = 45000         # faq 上限
_MEETINGS_DOC_BUDGET = 40000    # meetings 上限


def _doc_budget(kind: str) -> int:
    return {
        "base": _KNOWLEDGE_DOC_BUDGET,
        "faq": _FAQ_DOC_BUDGET,
        "meetings": _MEETINGS_DOC_BUDGET,
    }.get(kind, 60000)


_DOC_HEADERS = {
    "base": "【社内ナレッジ資料（商品・料金・サービス）】",
    "faq": "",        # FAQブロックは自前の見出しを持つ
    "meetings": "",   # 議事録ブロックも自前の見出しを持つ
}


# --------------------------------------------------------------------------- #
# バックエンド判定
# --------------------------------------------------------------------------- #
def _use_gcs() -> bool:
    return bool(settings.GCS_BUCKET)


def _bucket():
    """GCS バケットを返す（google-cloud-storage は遅延 import）。"""
    from google.cloud import storage  # type: ignore

    client = storage.Client()
    return client.bucket(settings.GCS_BUCKET)


def _gcs_path(*parts: str) -> str:
    return "/".join([settings.GCS_PREFIX, *parts]).strip("/")


# --------------------------------------------------------------------------- #
# ローカル用ヘルパ
# --------------------------------------------------------------------------- #
def _ensure_dirs() -> None:
    settings.REFERENCE_TALKS_DIR.mkdir(parents=True, exist_ok=True)
    settings.EVALUATIONS_DIR.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# 模範トーク（複数を蓄積し、評価の🎯模範トーク視点の基準にする）
# --------------------------------------------------------------------------- #
_REFERENCE_JSON_NAME = "reference.json"
# 模範トークの保持上限と、評価プロンプトへ渡す合計文字数の上限（トークン暴発防止）。
_REFERENCE_MAX_ITEMS = 20
_REFERENCE_CHAR_BUDGET = 12000


def _reference_json_path() -> Path:
    return settings.DATA_DIR / _REFERENCE_JSON_NAME


def _load_reference() -> list[dict]:
    # 永続化先：シート → GCS → ローカル（弊社ナレッジと同じ優先順）
    if _use_sheets():
        from services import sheets_knowledge

        try:
            return sheets_knowledge.load_reference()
        except Exception:
            return []
    if _use_gcs():
        blob = _bucket().blob(_gcs_path(_REFERENCE_JSON_NAME))
        if not blob.exists():
            return []
        try:
            return json.loads(blob.download_as_text())
        except (json.JSONDecodeError, OSError):
            return []
    path = _reference_json_path()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_reference(items: list[dict]) -> None:
    if _use_sheets():
        from services import sheets_knowledge

        sheets_knowledge.save_reference(items)
        return
    payload = json.dumps(items, ensure_ascii=False, indent=2)
    if _use_gcs():
        _bucket().blob(_gcs_path(_REFERENCE_JSON_NAME)).upload_from_string(
            payload, content_type="application/json"
        )
        return
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _reference_json_path().write_text(payload, encoding="utf-8")


def add_reference_talk(text: str, label: str = "") -> None:
    """手入力など、完成済みの模範トークテキストを1件 蓄積する。"""
    text = (text or "").strip()
    if not text:
        return
    items = _load_reference()
    items.append({
        "id": "manual_" + time.strftime("%Y%m%d%H%M%S"),
        "label": label,
        "status": "done",
        "text": text,
        "added_at": _now_jst_str(),
    })
    _save_reference(items[-_REFERENCE_MAX_ITEMS:])


def start_reference_job(job_id: str, label: str = "") -> None:
    """ドライブ録画の文字起こし開始時に『処理中』の枠を1件作る。"""
    items = _load_reference()
    items.append({
        "id": job_id,
        "label": label,
        "status": "processing",
        "text": "",
        "added_at": _now_jst_str(),
    })
    _save_reference(items[-_REFERENCE_MAX_ITEMS:])


def _update_reference(job_id: str, **changes) -> None:
    items = _load_reference()
    for it in items:
        if it.get("id") == job_id:
            it.update(changes)
            break
    _save_reference(items)


def finish_reference(job_id: str, text: str) -> None:
    _update_reference(job_id, status="done", text=(text or "").strip())


def fail_reference(job_id: str, error: str) -> None:
    _update_reference(job_id, status="error", error=error)


def list_reference_talks() -> list[dict]:
    """蓄積された模範トーク（処理中・失敗も含む）を返す。"""
    return _load_reference()


def delete_reference_talk(job_id: str) -> None:
    items = [it for it in _load_reference() if it.get("id") != job_id]
    _save_reference(items)


def clear_reference_talks() -> None:
    _save_reference([])


def get_reference_talk() -> str | None:
    """評価プロンプトへ渡す模範トーク基準（複数を結合、合計文字数で上限）。"""
    items = [it for it in _load_reference() if it.get("status", "done") == "done" and it.get("text")]
    if not items:
        return None
    parts: list[str] = []
    total = 0
    # 新しいものを優先して合計文字数の上限まで詰める
    for it in reversed(items):
        head = f"■ 模範トーク{(' [' + it['label'] + ']') if it.get('label') else ''}"
        block = f"{head}\n{it['text']}"
        if parts and total + len(block) > _REFERENCE_CHAR_BUDGET:
            break
        parts.append(block)
        total += len(block)
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- #
# 弊社ナレッジ（過去商談から蓄積する社内知識）
# --------------------------------------------------------------------------- #
_CATEGORY_LABELS = {
    "product": "商品知識",
    "rule": "社内ルール",
    "technique": "トーク技術",
}


def _knowledge_path() -> Path:
    return settings.DATA_DIR / _KNOWLEDGE_NAME


def _use_sheets() -> bool:
    """弊社ナレッジを Google スプレッドシートに永続保存する設定か。"""
    from services import sheets_knowledge

    return sheets_knowledge.configured()


def _load_knowledge() -> list[dict]:
    # 最優先：共有ドライブのスプレッドシート（再起動でも消えない弊社の頭脳）
    if _use_sheets():
        from services import sheets_knowledge

        try:
            return sheets_knowledge.load()
        except Exception:
            # シート障害時も評価自体は止めない（知識なしで続行）
            return []
    if _use_gcs():
        blob = _bucket().blob(_gcs_path(_KNOWLEDGE_NAME))
        if not blob.exists():
            return []
        try:
            return json.loads(blob.download_as_text())
        except (json.JSONDecodeError, OSError):
            return []
    path = _knowledge_path()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_knowledge(items: list[dict]) -> None:
    if _use_sheets():
        from services import sheets_knowledge

        sheets_knowledge.save(items)
        return
    payload = json.dumps(items, ensure_ascii=False, indent=2)
    if _use_gcs():
        _bucket().blob(_gcs_path(_KNOWLEDGE_NAME)).upload_from_string(
            payload, content_type="application/json"
        )
        return
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _knowledge_path().write_text(payload, encoding="utf-8")


def append_knowledge(items: list[KnowledgeItem]) -> int:
    """抽出した知識を蓄積する。重複は除外し、上限を超えたら古いものから間引く。

    追加された新規件数を返す。
    """
    if not items:
        return 0
    existing = _load_knowledge()
    seen = {(_norm(e.get("point", ""))) for e in existing}
    added = 0
    for it in items:
        point = (it.point or "").strip()
        if not point or _norm(point) in seen:
            continue
        existing.append({"category": it.category, "point": point})
        seen.add(_norm(point))
        added += 1
    if added:
        # 上限超過分は古い方（先頭）から落とす
        existing = existing[-_KNOWLEDGE_MAX_ITEMS:]
        _save_knowledge(existing)
    return added


def _norm(text: str) -> str:
    return "".join(text.split()).lower()


def add_knowledge_item(category: str, point: str) -> bool:
    """手入力で知識を1件追加する（重複は弾く）。追加できたら True。"""
    point = (point or "").strip()
    if not point:
        return False
    items = _load_knowledge()
    if any(_norm(i.get("point", "")) == _norm(point) for i in items):
        return False
    items.append({"category": category, "point": point})
    _save_knowledge(items[-_KNOWLEDGE_MAX_ITEMS:])
    return True


def update_knowledge_item(old_point: str, category: str, point: str) -> bool:
    """既存の知識1件を手入力で修正する（old_point で特定）。成功で True。"""
    point = (point or "").strip()
    if not point:
        return False
    items = _load_knowledge()
    for it in items:
        if it.get("point", "") == old_point:
            it["category"] = category
            it["point"] = point
            _save_knowledge(items)
            return True
    return False


def delete_knowledge_item(point: str) -> bool:
    """知識1件を削除する（point で特定）。削除できたら True。"""
    items = _load_knowledge()
    remaining = [i for i in items if i.get("point", "") != point]
    if len(remaining) == len(items):
        return False
    _save_knowledge(remaining)
    return True


def get_knowledge_items() -> list[dict]:
    """蓄積された知識を返す（カテゴリ・内容の dict のリスト）。"""
    return _load_knowledge()


# --- 社内ナレッジ資料（base=整備版 / faq / meetings の3セクション）-------------- #
_DOC_CACHE: dict[str, tuple[float, str]] = {}
_DOC_CACHE_TTL = 300.0  # 参照ドキュメント読み取りの短時間キャッシュ秒数（編集時は即破棄）


def _invalidate_doc_cache() -> None:
    """参照ドキュメントのキャッシュを破棄する（編集・保存の直後に呼ぶ）。"""
    _DOC_CACHE.clear()


def _load_knowledge_doc(kind: str = "base") -> str:
    """参照ドキュメント（シナリオ/カンペ/模範トーク/写真/ナレッジ）を読む。

    ロープレのシーン切替のたびに複数回シートを読みに行くとラグになるため、
    短時間だけプロセス内キャッシュする。**AI評価や評価履歴の読み取りには一切関与せず**、
    参照テキストの取得だけを速くするので、評価の精度には影響しない。編集時は
    set 側で `_invalidate_doc_cache()` を呼んで即座に最新へ切り替える。
    """
    hit = _DOC_CACHE.get(kind)
    if hit and hit[0] > time.time():
        return hit[1]
    val = _load_knowledge_doc_uncached(kind)
    _DOC_CACHE[kind] = (time.time() + _DOC_CACHE_TTL, val)
    return val


def _load_knowledge_doc_uncached(kind: str = "base") -> str:
    name, tab = _DOC_KINDS[kind]
    if _use_sheets():
        from services import sheets_knowledge

        try:
            return sheets_knowledge.load_doc(tab)
        except Exception:
            return ""
    if _use_gcs():
        blob = _bucket().blob(_gcs_path(name))
        if not blob.exists():
            return ""
        try:
            return blob.download_as_text()
        except OSError:
            return ""
    path = settings.DATA_DIR / name
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def set_knowledge_doc(text: str, kind: str = "base") -> None:
    """社内ナレッジ資料テキストを丸ごと保存する（該当セクションを置き換える）。"""
    text = (text or "").strip()
    _invalidate_doc_cache()  # 保存したら読み取りキャッシュを破棄して即座に反映させる
    name, tab = _DOC_KINDS[kind]
    if _use_sheets():
        from services import sheets_knowledge

        sheets_knowledge.save_doc(text, tab)
        return
    if _use_gcs():
        _bucket().blob(_gcs_path(name)).upload_from_string(
            text, content_type="text/plain; charset=utf-8"
        )
        return
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    (settings.DATA_DIR / name).write_text(text, encoding="utf-8")


def get_knowledge_doc(kind: str = "base") -> str:
    """保存済みの社内ナレッジ資料テキストを返す（無ければ空文字）。"""
    return _load_knowledge_doc(kind)


def clear_knowledge_doc(kind: str = "base") -> None:
    """社内ナレッジ資料を消す（管理者操作）。"""
    set_knowledge_doc("", kind)


# --- 商談議事録から抽出した実践知（増分処理＋重要度順の蒸留）------------------- #
_MEET_JSON_NAME = "meeting_insights.json"
_MEET_MAX_DISTILL = 220  # meetings セクションに展開する最大件数

_MEET_CAT_LABELS = {
    "product": "商品知識",
    "rule": "社内ルール・運用",
    "technique": "トーク技術",
    "customer": "お客様の不安・反応パターン",
}


def _load_meeting_insights() -> list[dict]:
    if _use_sheets():
        from services import sheets_knowledge

        try:
            return sheets_knowledge.load_meeting_insights()
        except Exception:
            return []
    if _use_gcs():
        blob = _bucket().blob(_gcs_path(_MEET_JSON_NAME))
        if not blob.exists():
            return []
        try:
            return json.loads(blob.download_as_text())
        except (json.JSONDecodeError, OSError):
            return []
    path = settings.DATA_DIR / _MEET_JSON_NAME
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_meeting_insights(items: list[dict]) -> None:
    if _use_sheets():
        from services import sheets_knowledge

        sheets_knowledge.save_meeting_insights(items)
        return
    payload = json.dumps(items, ensure_ascii=False, indent=2)
    if _use_gcs():
        _bucket().blob(_gcs_path(_MEET_JSON_NAME)).upload_from_string(
            payload, content_type="application/json"
        )
        return
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    (settings.DATA_DIR / _MEET_JSON_NAME).write_text(payload, encoding="utf-8")


def get_processed_meeting_ids() -> set:
    """すでに抽出済みの議事録ファイルIDの集合（再処理スキップ用）。"""
    return {it.get("doc_id", "") for it in _load_meeting_insights() if it.get("doc_id")}


def count_meeting_insights() -> int:
    return sum(1 for it in _load_meeting_insights() if (it.get("insight") or "").strip())


def add_meeting_insights(doc_id: str, items: list[dict]) -> int:
    """1つの議事録から抽出した知見を追記する（知見0件でも処理済みとして記録）。"""
    existing = _load_meeting_insights()
    now = _now_jst_str()
    added = 0
    for it in items:
        insight = (it.get("insight") or "").strip()
        if not insight:
            continue
        existing.append({
            "doc_id": doc_id,
            "category": (it.get("category") or "").strip(),
            "insight": insight,
            "importance": str(it.get("importance", "")),
            "added_at": now,
        })
        added += 1
    if added == 0:
        # 知見ゼロでも処理済みマーカーを残す
        existing.append({
            "doc_id": doc_id, "category": "", "insight": "",
            "importance": "", "added_at": now,
        })
    _save_meeting_insights(existing)
    return added


def distill_meeting_knowledge() -> int:
    """蓄積した議事録の知見を重複統合・重要度順に圧縮して meetings セクションへ展開する。"""
    raw = [it for it in _load_meeting_insights() if (it.get("insight") or "").strip()]
    merged: dict = {}
    for it in raw:
        key = _norm(it["insight"])
        try:
            imp = int(float(it.get("importance") or 0))
        except (TypeError, ValueError):
            imp = 0
        if key not in merged:
            merged[key] = {
                "category": it.get("category", ""),
                "insight": it["insight"].strip(),
                "importance": imp,
                "freq": 1,
            }
        else:
            m = merged[key]
            m["importance"] = max(m["importance"], imp)
            m["freq"] += 1
    ranked = sorted(merged.values(), key=lambda x: (-x["importance"], -x["freq"]))

    lines = ["===== 商談議事録から学んだ実践知（重要度順・個人情報は除外） ====="]
    total = len(lines[0])
    count = 0
    for r in ranked:
        if count >= _MEET_MAX_DISTILL:
            break
        label = _MEET_CAT_LABELS.get(r["category"], r["category"] or "その他")
        line = f"[{label}] {r['insight']}"
        if total + len(line) + 1 > _MEETINGS_DOC_BUDGET:
            break
        lines.append(line)
        total += len(line) + 1
        count += 1
    set_knowledge_doc("\n".join(lines) if count else "", kind="meetings")
    return count


# --- 1人ロープレ：模範トークスクリプト と シナリオ台本 ------------------------- #
# 会話中はAIを呼ばず台本で進めるため、無料枠でも1セッション＝Gemini1回で済む。
_DEFAULT_SCENARIOS = [
    {
        "id": "first_meeting",
        "title": "初回商談（ヒアリング〜提案の入口）",
        "turns": [
            {
                "customer": "はじめまして。今日はよろしくお願いします。……正直、オプションって何を頼めばいいのか、よく分かっていなくて。",
                "hint": "・まず感謝＋安心づけ（『分からなくて当然です』と受け止める）\n"
                        "・今日のゴールを共有（今日は決める場ではなく、選択肢を知る場）\n"
                        "・オプション会は説明が薄く“やるやらない”を迫られがち、と先回りで伝える\n"
                        "例）「大丈夫です、皆さん最初はそうです。今日は決める場ではなく、"
                        "どんな選択肢があるかを知っていただく場だと思ってください」",
            },
            {
                "customer": "なるほど。ただ、マンションのオプション会でも似た話を聞いたんですが、あちらより高くなったりしませんか？",
                "hint": "・価格だけでなく“中身の違い”に土俵を移す（グレード・耐久年数・保証）\n"
                        "・オプション会は説明が短く比較しづらいことを具体的に\n"
                        "・弊社は実見積ベースで、内覧会採寸後に正式見積で確定と伝える\n"
                        "例）「同じ“コーティング”でも種類で耐久年数が全然違うんです。"
                        "そこを比べられるようにお出しします」",
            },
            {
                "customer": "うーん、予算もあるので……。実際、どのくらいかかるものなんでしょうか。",
                "hint": "・即答で数字を投げず、まず範囲と決まり方を説明（寸法で変動）\n"
                        "・概算→内覧会で採寸→正式見積、の流れを明示\n"
                        "・費用が発生する前なら何度でも見直せる、と不安を下げる\n"
                        "例）「概算は間取り図の寸法で作り、正式は内覧会の採寸後に確定します。"
                        "費用が出る前なら何度でも変更できます」",
            },
            {
                "customer": "そうなんですね。ちょっと妻とも相談したいので、今日は決めきれないかもしれません。",
                "hint": "・持ち帰りを歓迎する（迫らない）＝信頼が上がる\n"
                        "・奥様が判断しやすい材料（写真・事例・比較）を用意すると申し出る\n"
                        "・ショールームで実物を見る選択肢を提示\n"
                        "例）「もちろんです。奥様が見て分かるように、事例写真と比較表をお送りしますね」",
            },
            {
                "customer": "分かりました。ではまず見積もりだけ、お願いできますか。",
                "hint": "・次の一歩を具体化（いつまでに出す・何が必要か）\n"
                        "・内覧会同行（無料）の案内で次の接点を作る＝先着・予約制\n"
                        "例）「1週間以内にお出しします。あわせて内覧会の同行が無料でできるので、"
                        "日程が決まったらお知らせください。予約制で埋まりやすいです」",
            },
        ],
    },
    {
        "id": "objection",
        "title": "反論対応（価格・他社比較・先延ばし）",
        "turns": [
            {
                "customer": "お話は分かったんですが、正直ちょっと高いなという印象です。",
                "hint": "・否定せず一度受け止める（『そう感じますよね』）\n"
                        "・“高い”の中身を確認（総額？他と比べて？予算枠？）＝秘密領域を開く\n"
                        "・価格ではなく耐久年数・手入れの手間で価値を再提示\n"
                        "例）「率直に言っていただけて助かります。どのあたりが引っかかりますか？」",
            },
            {
                "customer": "他社さんでも同じような施工をやっていて、そちらの方が安かったんですよね。",
                "hint": "・他社を否定しない（下げると信頼を失う）\n"
                        "・比較軸を提示（コーティングの種類・保証・施工範囲・特典）\n"
                        "・同条件で見比べられる形にして差を可視化\n"
                        "例）「良いと思います。ただ種類が違うと年数が変わるので、"
                        "同じ条件で見比べられるようにしますね」",
            },
            {
                "customer": "急いでいないので、入居してから考えても良いかなと思っていて。",
                "hint": "・入居前しかできない工事がある点を事実として伝える（家具搬入前）\n"
                        "・後からだと費用・手間が増える具体例\n"
                        "・急かさず“判断材料”として置く\n"
                        "例）「実は施工は原則お引渡し前・家具の搬入前なんです。"
                        "入居後だと動かす手間や追加費用が出やすくて」",
            },
            {
                "customer": "主人が『今は要らないんじゃないか』と言っていて、説得できる自信がなくて。",
                "hint": "・説得役を奥様に負わせない（こちらが材料を用意する）\n"
                        "・ご主人が納得しやすい観点（費用対効果・耐久・ресale）で資料化\n"
                        "・同席オンラインの提案\n"
                        "例）「説得はこちらでやります。ご主人が見て判断できる比較資料をお渡ししますね。"
                        "よければ一緒にオンラインでもご説明します」",
            },
        ],
    },
    {
        "id": "closing",
        "title": "クロージング（決断の後押し）",
        "turns": [
            {
                "customer": "内容はだいたい理解できました。あとは決めるだけ、という感じですね。",
                "hint": "・要点を短く要約して合意を取る（認識ズレを潰す）\n"
                        "・決めることを明確化（種類・範囲・時期）\n"
                        "例）「では確認ですね。◯◯を△△の範囲で、内覧会後に確定という形で合っていますか？」",
            },
            {
                "customer": "ただ、本当にこの内容で足りるのか、少し不安があります。",
                "hint": "・不安を具体化する質問（どこが足りない気がするか）＝秘密領域\n"
                        "・実際の事例で“よくある追加”を先に伝える\n"
                        "例）「どのあたりが引っかかりますか？似たお住まいだと◯◯を足す方が多いです」",
            },
            {
                "customer": "もし後から追加したくなったら、どうなりますか？",
                "hint": "・内覧会採寸後の正式見積までは変更可能と伝える\n"
                        "・後追加の可否と条件（時期で費用が変わる）を正直に\n"
                        "例）「内覧会の採寸で正式見積を出すので、それまでは何度でも調整できます」",
            },
            {
                "customer": "分かりました。では、進める方向で考えます。",
                "hint": "・次アクションを日付で確定（いつ見積、いつ内覧会、いつ返事）\n"
                        "・内覧会同行の予約を促す（先着・予約制）\n"
                        "例）「ありがとうございます。見積は◯日までにお送りします。"
                        "内覧会の日程が出たらすぐご連絡ください、予約が埋まりやすいので」",
            },
        ],
    },
]


def scenario_turns(scenario: dict) -> list[dict]:
    """シナリオを [{customer, hint}] に正規化する（旧 lines 形式にも対応）。

    ターンに `variants`（切り口違いの雑談パターン等）があればそのまま保持する。
    どのパターンを使うかの選出は app 側（セッション内で固定できる場所）で行う。
    """
    turns = scenario.get("turns")
    if isinstance(turns, list) and turns:
        out = []
        for t in turns:
            if not t.get("customer"):
                continue
            row = {"customer": str(t.get("customer", "")), "hint": str(t.get("hint", ""))}
            variants = t.get("variants")
            if isinstance(variants, list) and variants:
                row["variants"] = variants
            out.append(row)
        return out
    return [{"customer": str(t), "hint": ""} for t in scenario.get("lines", []) if t]


_SCRIPT_ITEMS_NAME = "talk_scripts.json"
_SCRIPT_DOC_HEADER = "===== 模範トークスクリプト（社内標準） ====="

# 単元（タブ）をロープレのカテゴリに分類する（編集画面・シナリオ生成で共通利用）。
# 判定はこの順（商材を先に、汎用の「導入」は最後）。4カテゴリ外は「その他」。
SCRIPT_CATEGORY_ORDER = ["導入", "コーティング", "エコカラット", "ダウンライト", "実践ロープレ", "その他"]
_SCRIPT_CATEGORY_KEYS = [
    ("コーティング", ["コーティング", "ガラス説明", "ＵＶ説明", "UV説明", "シリコン説明",
                     "セラミック説明", "整い", "水回りコーティング", "水廻り", "フロアコーティング"]),
    ("エコカラット", ["エコカラット", "エコＬＤ", "エコLD"]),
    ("ダウンライト", ["ダウンライト", "人感センサー", "照明"]),
    ("導入", ["導入", "会社説明", "内覧会", "締め", "スケジュール", "引っ越し", "引越",
             "検討内容", "商談の流れ"]),
]


def script_category(tab: str) -> str:
    """単元名からロープレのカテゴリを返す（4カテゴリ or その他）。"""
    for name, keys in _SCRIPT_CATEGORY_KEYS:
        if any(k in (tab or "") for k in keys):
            return name
    return "その他"


def get_talk_script_items() -> list[dict]:
    """模範トークスクリプトを『単元（元スプシのタブ）ごと』に返す。

    各要素: {book, tab, body}。中身をタブ単位で確認・修正できるようにするため、
    連結テキストではなく単元ごとに保持する。
    """
    if _use_sheets():
        from services import sheets_knowledge

        try:
            return sheets_knowledge.load_talk_scripts()
        except Exception:
            return []
    path = settings.DATA_DIR / _SCRIPT_ITEMS_NAME
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def set_talk_script_items(items: list[dict]) -> None:
    """単元ごとの模範トークスクリプトを保存する。"""
    if _use_sheets():
        from services import sheets_knowledge

        sheets_knowledge.save_talk_scripts(items)
        return
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    (settings.DATA_DIR / _SCRIPT_ITEMS_NAME).write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def update_talk_script_item(tab: str, body: str) -> bool:
    """単元1つの本文を差し替える（内容チェック後の修正用）。"""
    items = get_talk_script_items()
    for it in items:
        if it.get("tab") == tab:
            it["body"] = body
            set_talk_script_items(items)
            return True
    return False


def get_talk_script() -> str:
    """評価プロンプトへ渡す模範トークスクリプト（単元を連結した全文）。"""
    items = get_talk_script_items()
    if items:
        parts = [_SCRIPT_DOC_HEADER]
        book = None
        for it in items:
            if it.get("book") and it["book"] != book:
                book = it["book"]
                parts.append(f"\n──────── 【{book}】 ────────")
            parts.append(f"\n■ {it.get('tab','')}\n{it.get('body','')}")
        return "\n".join(parts)
    # 後方互換：1本のテキストで登録されている場合
    return _load_knowledge_doc("script")


def set_talk_script(text: str) -> None:
    """手入力の1本テキストで登録する（単元は『手入力』としてまとめる）。"""
    text = (text or "").strip()
    if not text:
        set_talk_script_items([])
        set_knowledge_doc("", kind="script")
        return
    set_talk_script_items([{"book": "手入力", "tab": "手入力スクリプト", "body": text}])


def get_scenarios() -> list[dict]:
    """ロープレのシナリオ台本。未登録なら既定シナリオを返す。"""
    raw = _load_knowledge_doc("scenarios").strip()
    if raw:
        try:
            items = json.loads(raw)
            if isinstance(items, list) and items:
                return items
        except json.JSONDecodeError:
            pass
    return _DEFAULT_SCENARIOS


def set_scenarios(items: list[dict]) -> None:
    set_knowledge_doc(json.dumps(items, ensure_ascii=False, indent=2), kind="scenarios")


def get_scenario(scenario_id: str) -> dict | None:
    return next((s for s in get_scenarios() if s.get("id") == scenario_id), None)


# 検討済みのお客様が、その商材を具体的に検討している体の第一声（カテゴリ一致を保証）。
_DECIDED_OPENING = {
    "コーティング": "コーティングを検討していて、見積もりももらったんですが、種類の違いを教えてもらえますか？",
    "エコカラット": "エコカラットを検討していて、いくつか見積もりも取っているんですが、特徴を教えてもらえますか？",
    "ダウンライト": "ダウンライトや照明の変更を検討しているんですが、どんなことができるか教えてもらえますか？",
}


# --- 管理者による上書きレイヤー（お客様セリフ・カンペ）--------------------------- #
# 構造: { "<scenario_id>": { "<turn_index>": {"customer": .., "hint": ..} } }
# 指定フィールドのみ上書きし、未指定（または空文字）は元の台本のまま残す。
# シナリオを再生成しても別ドキュメントに保存されるため、この編集は消えない。
def set_scenario_overrides(overrides: dict) -> None:
    set_knowledge_doc(json.dumps(overrides, ensure_ascii=False), kind="overrides")


def get_scenario_overrides() -> dict:
    raw = _load_knowledge_doc("overrides").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def update_scenario_turn_override(
    scenario_id: str,
    turn_index: int,
    *,
    customer: str | None = None,
    hint: str | None = None,
) -> None:
    """1ターン分の上書きを保存する（None のフィールドは変更しない）。

    customer/hint に空文字を渡すと「元の台本に戻す」意味になる（適用時に空は無視するため）。
    実質的に空になった要素は保存前に掃除する。
    """
    overrides = get_scenario_overrides()
    sc = overrides.setdefault(scenario_id, {})
    turn = sc.setdefault(str(turn_index), {})
    if customer is not None:
        turn["customer"] = customer
    if hint is not None:
        turn["hint"] = hint
    if not ((turn.get("customer") or "").strip() or (turn.get("hint") or "").strip()):
        sc.pop(str(turn_index), None)
    if not sc:
        overrides.pop(scenario_id, None)
    set_scenario_overrides(overrides)


# --- 単元（カテゴリ|タイトル）ごとの「お客様に見せるフック写真」----------------- #
# 目的：練習中の単元に合わせて 1 枚の施工事例写真を表示するだけ。外部フォルダ不要。
# 保存：縮小JPEG（最長辺480px・品質65）を base64 にして知識シートへ。save_doc が
#       行分割で保存するためセル上限に当たらない。大きな写真でも落ちない設計。
_UNIT_PHOTO_MAX_EDGE = 480
_UNIT_PHOTO_QUALITY = 65


def unit_photo_key(scenario: dict) -> str:
    """単元の写真キー f'{group}|{title}'（検討済み/未検討で同じ写真を共有する）。"""
    return f"{scenario.get('group', '')}|{scenario.get('title', '')}"


def get_unit_photos() -> dict:
    raw = _load_knowledge_doc("unit_photos").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _save_unit_photos(photos: dict) -> None:
    set_knowledge_doc(json.dumps(photos, ensure_ascii=False), kind="unit_photos")


def set_unit_photo(key: str, data: bytes) -> bool:
    """単元のフック写真を縮小JPEG→base64で保存する。成功なら True。

    大きな画像でもアプリを落とさないため、縮小・エンコードに失敗したら保存せず False を返す
    （呼び出し側で警告表示）。Pillow は Streamlit 同梱。
    """
    import base64
    import io as _io

    try:
        from PIL import Image
    except Exception:
        return False
    try:
        img = Image.open(_io.BytesIO(data))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((_UNIT_PHOTO_MAX_EDGE, _UNIT_PHOTO_MAX_EDGE))
        buf = _io.BytesIO()
        img.save(buf, format="JPEG", quality=_UNIT_PHOTO_QUALITY, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return False
    photos = get_unit_photos()
    photos[key] = {"b64": b64, "mime": "image/jpeg"}
    _save_unit_photos(photos)
    return True


def get_unit_photo(key: str) -> bytes | None:
    """単元のフック写真のバイト列を返す（無ければ None）。"""
    import base64

    ent = get_unit_photos().get(key)
    b64 = ent.get("b64") if isinstance(ent, dict) else ent
    if not b64:
        return None
    try:
        return base64.b64decode(b64)
    except Exception:
        return None


def delete_unit_photo(key: str) -> None:
    photos = get_unit_photos()
    if key in photos:
        photos.pop(key, None)
        _save_unit_photos(photos)


def persona_flavored_turns(scenario: dict) -> list[dict]:
    """台本のターンに、議事録由来のお客様ペルソナの“生の言い回し”を混ぜて返す。

    - 決定的（同じ単元なら毎回同じ）なので、画面表示と評価で結果が一致する。
    - 検討済み×商材カテゴリは、そのカテゴリに合った具体的な第一声にする（不一致を防ぐ）。
    - 未検討・導入は、受け身/汎用のペルソナ第一声を使う。
    """
    turns = scenario_turns(scenario)
    if not turns:
        return turns

    # --- 管理者の上書きレイヤー（お客様セリフ・カンペ）を最初に適用する ---------- #
    # keep_opening（手作り単元）にも自動生成単元にも効かせるため、早期returnより前で適用。
    # 指定フィールドのみ差し替え、空文字の customer/hint は「元の台本のまま」を意味し
    # 上書きしない。どのターンで hint/customer を上書きしたかを記録し、後段のペルソナ
    # 第一声・コーチング前置きが管理者の編集を潰さないようにする。
    turns = [dict(t) for t in turns]
    sc_ov = get_scenario_overrides().get(scenario.get("id", ""), {})
    overridden_customer: set[int] = set()
    overridden_hint: set[int] = set()
    if isinstance(sc_ov, dict):
        for idx, t in enumerate(turns):
            o = sc_ov.get(str(idx))
            if not isinstance(o, dict):
                continue
            if (o.get("customer") or "").strip():
                t["customer"] = o["customer"]
                overridden_customer.add(idx)
            if (o.get("hint") or "").strip():
                t["hint"] = o["hint"]
                overridden_hint.add(idx)

    # 手作り単元（ラポール等）は第一声・カンペをそのまま使う（上書き適用済みを返す）
    if scenario.get("keep_opening"):
        return turns
    persona = get_customer_persona()
    cat = scenario.get("group", "")
    undecided = scenario.get("customer_type") == "未検討"

    line = None
    if not undecided and cat in _DECIDED_OPENING:
        line = _DECIDED_OPENING[cat]
    else:
        key = "undecided" if undecided else "decided"
        p = persona.get(key, {}) if isinstance(persona, dict) else {}
        openings = [o for o in (p.get("opening") or []) if o]
        if openings:
            seed = sum(ord(c) for c in scenario.get("id", "")) % len(openings)
            line = openings[seed]
    # 管理者が第一声を上書きしている場合は、ペルソナ第一声で上書きしない（編集を尊重）
    if line and 0 not in overridden_customer:
        turns[0] = dict(turns[0])
        turns[0]["customer"] = line

    # カンペ冒頭に「進め方の切り口」コーチングを差し込む（潜在ニーズを掘る導線を示す）。
    # 管理者がカンペを上書きしている場合は前置きしない（管理者の編集を優先・二重表示を防ぐ）。
    tips = get_coaching_tips()
    key = f"{cat}|{'未検討' if undecided else '検討済み'}"
    tip = (tips.get(key) or tips.get(cat) or "").strip()
    if tip and 0 not in overridden_hint:
        turns[0] = dict(turns[0])
        base_hint = turns[0].get("hint", "")
        turns[0]["hint"] = (
            "💡 進め方の切り口（AIコーチ）\n" + tip
            + "\n\n──────── 模範トーク ────────\n" + base_hint
        )
    return turns


_PERSONA_NAME = "customer_persona.json"


def set_customer_persona(persona: dict) -> None:
    """議事録から作ったお客様ペルソナ（属性別の反応・不安・口ぐせ・断り文句）を保存。"""
    set_knowledge_doc(json.dumps(persona, ensure_ascii=False), kind="persona")


def get_customer_persona() -> dict:
    raw = _load_knowledge_doc("persona").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def set_coaching_tips(tips: dict) -> None:
    """ロープレの『進め方の切り口』コーチング（キー="カテゴリ|属性"）を保存。"""
    set_knowledge_doc(json.dumps(tips, ensure_ascii=False), kind="coaching")


def get_coaching_tips() -> dict:
    raw = _load_knowledge_doc("coaching").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def clear_meeting_insights() -> None:
    """議事録の知見・処理済み記録をすべて消す（管理者操作）。"""
    _save_meeting_insights([])
    set_knowledge_doc("", kind="meetings")


def get_knowledge_base() -> str | None:
    """評価プロンプトへ渡す『弊社ナレッジ』テキストを返す（無ければ None）。

    base（整備版資料）＋ faq（FAQ抜粋）＋ meetings（議事録の実践知）＋ 商談抽出知識。
    各セクションは文字数上限で切り詰めてトークン暴発を防ぐ。
    """
    sections: list[str] = []

    for kind in ("base", "faq", "meetings"):
        text = _load_knowledge_doc(kind).strip()
        if not text:
            continue
        header = _DOC_HEADERS[kind]
        body = text[: _doc_budget(kind)]
        sections.append(f"{header}\n{body}" if header else body)

    items = _load_knowledge()
    if items:
        lines: list[str] = []
        for cat in ("product", "rule", "technique"):
            group = [i["point"] for i in items if i.get("category") == cat]
            if not group:
                continue
            lines.append(f"【{_CATEGORY_LABELS[cat]}】")
            lines.extend(f"- {p}" for p in group)
        # カテゴリ未分類のものも拾う
        other = [i["point"] for i in items if i.get("category") not in _CATEGORY_LABELS]
        if other:
            lines.append("【その他】")
            lines.extend(f"- {p}" for p in other)
        if lines:
            sections.append("\n".join(lines))

    if not sections:
        return None
    return "\n\n".join(sections)


def clear_knowledge() -> None:
    """蓄積した知識をすべて消す（管理者操作）。"""
    _save_knowledge([])


# --------------------------------------------------------------------------- #
# 評価履歴
# --------------------------------------------------------------------------- #
def _safe(user_email: str) -> str:
    return user_email.replace("@", "_at_").replace("/", "_")


def _eval_handle(user_email: str, job_id: str) -> str:
    """この評価レコードの保存先（GCSオブジェクト名 or ローカルパス）を返す。"""
    fname = f"{_safe(user_email)}_{job_id}.json"
    if _use_gcs():
        return _gcs_path("evaluations", fname)
    return str(settings.EVALUATIONS_DIR / fname)


def _write_eval(handle: str, record: dict) -> None:
    payload = json.dumps(record, ensure_ascii=False, indent=2)
    if _use_gcs():
        _bucket().blob(handle).upload_from_string(
            payload, content_type="application/json"
        )
        return
    _ensure_dirs()
    Path(handle).write_text(payload, encoding="utf-8")


def _use_eval_sheets() -> bool:
    """評価履歴をスプレッドシートに永続保存する設定か（弊社ナレッジと同じSA）。"""
    return _use_sheets()


def _sheet_upsert_eval(record: dict) -> None:
    """スプレッドシートの評価行を job_id で更新（無ければ追加）して全置換保存する。"""
    from services import sheets_knowledge

    items = sheets_knowledge.load_evaluations()
    for it in items:
        if it.get("job_id") == record["job_id"]:
            it.update(record)
            break
    else:
        items.append(record)
    sheets_knowledge.save_evaluations(items)


def _eval_record(
    user_email: str, job_id: str, status: str, label: str,
    result: EvaluationResult | None = None, error: str = "",
) -> dict:
    return {
        "job_id": job_id,
        "user_email": user_email,
        "saved_at": _now_jst_str(),
        "status": status,
        "label": label,
        "result_json": json.dumps(result.to_dict(), ensure_ascii=False) if result else "",
        "error": error,
    }


def save_evaluation(user_email: str, result: EvaluationResult, label: str = "") -> str:
    """評価を一括保存する（完了状態）。"""
    job_id = time.strftime("%Y%m%d_%H%M%S")
    if _use_eval_sheets():
        _sheet_upsert_eval(_eval_record(user_email, job_id, "done", label, result=result))
        return job_id
    handle = _eval_handle(user_email, job_id)
    _write_eval(handle, {
        "user_email": user_email, "label": label,
        "saved_at": _now_jst_str(),
        "status": "done", "result": result.to_dict(),
    })
    return job_id


def start_evaluation(user_email: str, job_id: str, label: str = "") -> str:
    """解析開始時に『処理中』レコードを作る。"""
    if _use_eval_sheets():
        _sheet_upsert_eval(_eval_record(user_email, job_id, "processing", label))
        return job_id
    _write_eval(_eval_handle(user_email, job_id), {
        "user_email": user_email, "label": label,
        "saved_at": _now_jst_str(),
        "status": "processing", "result": None,
    })
    return job_id


def finish_evaluation(
    user_email: str, job_id: str, result: EvaluationResult, label: str = ""
) -> None:
    """背景解析の完了時に、同じレコードを『完了』へ更新する。"""
    if _use_eval_sheets():
        _sheet_upsert_eval(_eval_record(user_email, job_id, "done", label, result=result))
        return
    _write_eval(_eval_handle(user_email, job_id), {
        "user_email": user_email, "label": label,
        "saved_at": _now_jst_str(),
        "status": "done", "result": result.to_dict(),
    })


def fail_evaluation(
    user_email: str, job_id: str, error: str, label: str = ""
) -> None:
    """背景解析の失敗時に、同じレコードを『失敗』へ更新し、管理者へ通知する。"""
    if _use_eval_sheets():
        _sheet_upsert_eval(_eval_record(user_email, job_id, "error", label, error=error))
    else:
        _write_eval(_eval_handle(user_email, job_id), {
            "user_email": user_email, "label": label,
            "saved_at": _now_jst_str(),
            "status": "error", "error": error, "result": None,
        })
    _notify_admin_error(user_email, label, error)


def _notify_admin_error(user_email: str, label: str, error: str) -> None:
    """評価失敗を管理者へ Google Chat の個人DMで通知する（設定時のみ・失敗は無視）。"""
    try:
        admin = getattr(settings, "ERROR_NOTIFY_EMAIL", "")
        if not admin:
            return
        from services import google_chat
        who = (user_email or "").split("@")[0]
        text = ("⚠️ KNOTE 評価エラー\n"
                f"実施者: {who}\n対象: {label}\nエラー: {error}\n"
                "→ 評価履歴タブで確認してください。")
        google_chat.notify_admin(admin, text)
    except Exception:  # noqa: BLE001 通知失敗で本体を止めない
        pass


# 『処理中』のまま残った（再起動でスレッドが死んだ等）レコードを、この分数を超えたら
# 表示上はタイムアウト失敗として扱う。永遠に「判定中」が出続けるのを防ぐ。
_PROCESSING_TIMEOUT_MIN = 60


def _apply_processing_timeout(rec: dict) -> dict:
    """『処理中』が規定時間より古ければ、表示上は失敗（タイムアウト）に変える。"""
    if rec.get("status") != "processing":
        return rec
    saved = rec.get("saved_at", "")
    try:
        t = time.mktime(time.strptime(saved, "%Y-%m-%d %H:%M:%S"))
    except (ValueError, TypeError):
        return rec
    if (time.time() - t) > _PROCESSING_TIMEOUT_MIN * 60:
        rec = dict(rec)
        rec["status"] = "error"
        rec["error"] = (rec.get("error") or
                        "時間内に完了しませんでした（サーバー再起動や一時的な高負荷の可能性）。"
                        "もう一度評価してください。")
    return rec


def list_all_evaluations() -> list[dict]:
    """全メンバーの評価履歴を新しい順で返す（管理者の閲覧・実施状況の確認用）。"""
    if _use_eval_sheets():
        from services import sheets_knowledge

        rows = sorted(sheets_knowledge.load_evaluations(),
                      key=lambda r: r.get("job_id", ""), reverse=True)
        records = []
        for r in rows:
            rec = {
                "user_email": r.get("user_email", ""), "label": r.get("label", ""),
                "saved_at": r.get("saved_at", ""), "status": r.get("status", "done"),
                "error": r.get("error", ""), "result": None,
            }
            if r.get("result_json"):
                try:
                    rec["result"] = json.loads(r["result_json"])
                except json.JSONDecodeError:
                    rec["result"] = None
            records.append(_apply_processing_timeout(rec))
        return records

    if _use_gcs():
        records = []
        for blob in sorted(_bucket().list_blobs(prefix=_gcs_path("evaluations")),
                           key=lambda b: b.name, reverse=True):
            try:
                records.append(json.loads(blob.download_as_text()))
            except (json.JSONDecodeError, OSError):
                continue
        return [_apply_processing_timeout(r) for r in records]

    if not settings.EVALUATIONS_DIR.exists():
        return []
    records = []
    for path in sorted(settings.EVALUATIONS_DIR.glob("*.json"), reverse=True):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return [_apply_processing_timeout(r) for r in records]


def list_evaluations(user_email: str) -> list[dict]:
    """指定ユーザーの評価履歴を新しい順で返す（各自のみ。他人の評価は返さない）。"""
    if _use_eval_sheets():
        from services import sheets_knowledge

        rows = [r for r in sheets_knowledge.load_evaluations()
                if r.get("user_email") == user_email]
        rows.sort(key=lambda r: r.get("job_id", ""), reverse=True)
        records = []
        for r in rows:
            rec = {
                "user_email": r["user_email"], "label": r.get("label", ""),
                "saved_at": r.get("saved_at", ""), "status": r.get("status", "done"),
                "error": r.get("error", ""), "result": None,
            }
            if r.get("result_json"):
                try:
                    rec["result"] = json.loads(r["result_json"])
                except json.JSONDecodeError:
                    rec["result"] = None
            records.append(_apply_processing_timeout(rec))
        return records

    prefix_name = _safe(user_email)
    if _use_gcs():
        bucket = _bucket()
        blobs = list(bucket.list_blobs(prefix=_gcs_path("evaluations", prefix_name)))
        records = []
        for blob in sorted(blobs, key=lambda b: b.name, reverse=True):
            try:
                records.append(json.loads(blob.download_as_text()))
            except (json.JSONDecodeError, OSError):
                continue
        return records

    if not settings.EVALUATIONS_DIR.exists():
        return []
    records = []
    for path in sorted(
        settings.EVALUATIONS_DIR.glob(f"{prefix_name}_*.json"), reverse=True
    ):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return records
