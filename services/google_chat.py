"""Google Chat への通知（個人DM / スペースWebhook）。

ロープレ未実施者へ「本日まだですよ」を前向きに知らせるための送信層。認証情報は
すべて環境変数から読み、鍵やURLはコードに一切埋め込まない。

2つの経路を env の有無で自動選択する（configured() / _mode()）:

  A) 個人DM（推奨・アプリ認証）:
       - サービスアカウント（Chat アプリ）＋スコープ ``chat.bot`` で
         各ユーザーとの DM スペースに投稿する。
       - メール→ユーザーIDの解決に Directory API（``admin.directory.user.readonly``）を
         管理者 subject でドメイン全体委任（DWD）して使う。
       - 必要env: CHAT_SA_JSON か CHAT_SA_FILE、および CHAT_ADMIN_SUBJECT。
  B) Webhook フォールバック（手軽・スペース投稿）:
       - CHAT_WEBHOOK_URL があれば、DM の代わりにそのスペースへまとめて投稿する。
       - 管理者設定が重い DM が未整備でも動かせる簡易経路。

どちらも使えないときは configured() が False。呼び出し側（スクリプト）は
その場合に送信せず警告してスキップする（CI を赤くしない）。
"""
from __future__ import annotations

import json
import os

# Google Chat / Directory のスコープ。
_CHAT_SCOPES = ["https://www.googleapis.com/auth/chat.bot"]
_DIRECTORY_SCOPES = ["https://www.googleapis.com/auth/admin.directory.user.readonly"]


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _has_dm_config() -> bool:
    """個人DM経路（アプリ認証）に必要な env がそろっているか。"""
    return bool(
        (_env("CHAT_SA_JSON") or _env("CHAT_SA_FILE")) and _env("CHAT_ADMIN_SUBJECT")
    )


def _has_webhook_config() -> bool:
    return bool(_env("CHAT_WEBHOOK_URL"))


def _mode() -> str:
    """現在の送信モードを返す（"dm" / "webhook" / ""）。DMを優先する。"""
    if _has_dm_config():
        return "dm"
    if _has_webhook_config():
        return "webhook"
    return ""


def configured() -> bool:
    """いずれかの送信経路が使える設定か。"""
    return bool(_mode())


# --------------------------------------------------------------------------- #
# 認証（遅延 import：テスト・未設定時に依存を要求しない）
# --------------------------------------------------------------------------- #
def _sa_credentials(scopes: list[str], subject: str | None = None):
    """サービスアカウント Credentials を作る（CHAT_SA_JSON か CHAT_SA_FILE から）。"""
    from google.oauth2 import service_account

    if _env("CHAT_SA_JSON"):
        info = json.loads(_env("CHAT_SA_JSON"))
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=scopes
        )
    else:
        creds = service_account.Credentials.from_service_account_file(
            _env("CHAT_SA_FILE"), scopes=scopes
        )
    # Directory API は管理者になりすまして（DWD）呼ぶ必要がある。
    if subject:
        creds = creds.with_subject(subject)
    return creds


def _resolve_user_id(user_email: str) -> str:
    """メールアドレスを Chat 用のユーザーID（"users/1234..."）へ解決する。

    Directory API を管理者 subject でDWDして users().get で数値IDを引く。
    """
    from googleapiclient.discovery import build

    creds = _sa_credentials(_DIRECTORY_SCOPES, subject=_env("CHAT_ADMIN_SUBJECT"))
    directory = build("admin", "directory_v1", credentials=creds, cache_discovery=False)
    user = directory.users().get(userKey=user_email).execute()
    return f"users/{user['id']}"


def _chat_service():
    from googleapiclient.discovery import build

    creds = _sa_credentials(_CHAT_SCOPES)
    return build("chat", "v1", credentials=creds, cache_discovery=False)


# --------------------------------------------------------------------------- #
# 送信
# --------------------------------------------------------------------------- #
def _send_dm(user_email: str, text: str) -> None:
    """対象ユーザーとの DM スペースへ1件投稿する（アプリ認証）。"""
    service = _chat_service()
    user_id = _resolve_user_id(user_email)
    # 対象ユーザーとアプリの間のDMスペースを取得（無ければ Google 側が用意する）。
    dm = (
        service.spaces()
        .findDirectMessage(name=user_id)
        .execute()
    )
    space_name = dm["name"]
    service.spaces().messages().create(
        parent=space_name, body={"text": text}
    ).execute()


def _post_webhook(text: str) -> None:
    """CHAT_WEBHOOK_URL のスペースへ投稿する（フォールバック経路）。"""
    from urllib import request as _request

    payload = json.dumps({"text": text}).encode("utf-8")
    req = _request.Request(
        _env("CHAT_WEBHOOK_URL"),
        data=payload,
        headers={"Content-Type": "application/json; charset=UTF-8"},
        method="POST",
    )
    with _request.urlopen(req, timeout=15) as resp:  # noqa: S310 (URLは自社env)
        resp.read()


def send_dm(user_email: str, text: str) -> None:
    """対象ユーザーへ個人DMを送る（DM経路が設定済みのときのみ有効）。"""
    _send_dm(user_email, text)


def notify(email_to_text: dict[str, str]) -> dict:
    """複数人へ順次送信する。1件失敗しても続行し、成否を集計して返す。

    返り値:
        {"mode": "dm"|"webhook"|"", "sent": [...], "failed": [(email, error), ...],
         "skipped": bool}

    - DM経路: 各人へ個別DM。1件の例外では全体を止めない。
    - Webhook経路: 個別DMは張れないため、宛先ぶんを1通のスペース投稿にまとめる。
    - 未設定: 何もせず skipped=True を返す（例外は投げない）。
    """
    result: dict = {"mode": _mode(), "sent": [], "failed": [], "skipped": False}
    if not email_to_text:
        return result

    mode = result["mode"]
    if mode == "dm":
        for email, text in email_to_text.items():
            try:
                _send_dm(email, text)
                result["sent"].append(email)
            except Exception as e:  # noqa: BLE001 1件失敗でも他を続行
                result["failed"].append((email, str(e)[:200]))
        return result

    if mode == "webhook":
        # 個別DMが張れないので、まとめて1通のスペース投稿にする。
        lines = ["🎙️ 本日まだロープレ未実施の方へ"]
        lines += [text for text in email_to_text.values()]
        try:
            _post_webhook("\n".join(lines))
            result["sent"] = list(email_to_text.keys())
        except Exception as e:  # noqa: BLE001
            result["failed"] = [(email, str(e)[:200]) for email in email_to_text]
        return result

    # 未設定：送らずスキップ。
    result["skipped"] = True
    return result


def notify_admin(user_email: str, text: str) -> bool:
    """管理者1名へ通知する（DM経路優先／Webhookがあればそこへ素の本文で投稿）。

    リマインドと違い定型ヘッダは付けない（エラー通知等の任意用途向け）。
    未設定なら何もしない。例外は投げず、送れたら True を返す。
    """
    try:
        mode = _mode()
        if mode == "dm":
            _send_dm(user_email, text)
            return True
        if mode == "webhook":
            _post_webhook(text)
            return True
    except Exception:  # noqa: BLE001 通知失敗で本体を止めない
        pass
    return False
