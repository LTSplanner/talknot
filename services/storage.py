"""模範トーク・評価履歴の永続化。

保存先は2系統：
- `settings.GCS_BUCKET` が設定されていれば **Google Cloud Storage**（Cloud Run 等で
  再起動しても消えないようにする本番向け）。
- 未設定ならローカルファイル（`settings.DATA_DIR`。ローカル開発・テスト向け）。

入出力インターフェースをここに集約し、呼び出し側（app.py）は保存先を意識しない。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from config import settings
from core.models import EvaluationResult, KnowledgeItem

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
}
_KNOWLEDGE_DOC_BUDGET = 60000   # base 上限
_FAQ_DOC_BUDGET = 45000         # faq 上限
_MEETINGS_DOC_BUDGET = 40000    # meetings 上限


def _doc_budget(kind: str) -> int:
    return {
        "base": _KNOWLEDGE_DOC_BUDGET,
        "faq": _FAQ_DOC_BUDGET,
        "meetings": _MEETINGS_DOC_BUDGET,
    }[kind]


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
        "added_at": time.strftime("%Y-%m-%d %H:%M:%S"),
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
        "added_at": time.strftime("%Y-%m-%d %H:%M:%S"),
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
def _load_knowledge_doc(kind: str = "base") -> str:
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
    now = time.strftime("%Y-%m-%d %H:%M:%S")
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
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
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
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
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
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
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
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "done", "result": result.to_dict(),
    })


def fail_evaluation(
    user_email: str, job_id: str, error: str, label: str = ""
) -> None:
    """背景解析の失敗時に、同じレコードを『失敗』へ更新する。"""
    if _use_eval_sheets():
        _sheet_upsert_eval(_eval_record(user_email, job_id, "error", label, error=error))
        return
    _write_eval(_eval_handle(user_email, job_id), {
        "user_email": user_email, "label": label,
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "error", "error": error, "result": None,
    })


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
            records.append(rec)
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
