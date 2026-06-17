"""対話式で .env に秘密キーを安全に書き込むヘルパー。

入力は非表示（getpass）。空Enterで現状維持。チャットや履歴に値を残さない。

    python3 scripts/set_env.py
"""
from __future__ import annotations

from getpass import getpass
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

FIELDS = [
    ("GEMINI_API_KEY", "Gemini API キー"),
    ("GOOGLE_CLIENT_ID", "Google OAuth クライアント ID"),
    ("GOOGLE_CLIENT_SECRET", "Google OAuth クライアント シークレット"),
]


def _read() -> dict[str, str]:
    values: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    return values


def _write(updates: dict[str, str]) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    seen = set()
    out = []
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(line)
    for key, val in updates.items():
        if key not in seen:
            out.append(f"{key}={val}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    if not ENV_PATH.exists():
        print(".env が見つかりません。先に `cp .env.example .env` を実行してください。")
        return 1

    current = _read()
    print("=== .env への秘密キー設定（入力は非表示・空Enterで現状維持）===\n")
    updates: dict[str, str] = {}
    for key, label in FIELDS:
        has = "設定済み" if current.get(key) else "未設定"
        entered = getpass(f"{label} [{has}]: ").strip()
        if entered:
            updates[key] = entered

    if not updates:
        print("\n変更はありません。")
        return 0

    _write(updates)
    print("\n書き込み完了:")
    for key in updates:
        print(f"  {key}: 設定済み（{len(updates[key])}文字）")
    print("\n次は `python3 scripts/check_setup.py` で確認できます。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
