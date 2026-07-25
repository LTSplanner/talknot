"""Streamlit Community Cloud のスリープ防止（実ブラウザで起こす）。

Streamlit は「WebSocket セッションが張られたか」でアクティブ判定をするため、
単純な HTTP(curl) では“起きた”ことにならない。そこで Playwright(Chromium,
headless) で実際にページを開き、WebSocket セッションを張ってから数十秒滞在する。

アプリがスリープ済みなら「Yes, get this app back up!」のような起床ボタンが出る
ので、見つけたらクリックして復帰させる。

どんなエラーでも exit 0（GitHub Actions のジョブを失敗＝通知にしない）。
"""
from __future__ import annotations

import sys

APP_URL = "https://talknot-lts.streamlit.app"
# 起床ボタンの文言（Streamlit のスリープ画面）。表記揺れに備えて複数候補を順に探す。
WAKE_TEXTS = [
    "Yes, get this app back up",
    "get this app back up",
    "app back up",
]
DWELL_MS = 25_000  # WebSocket セッションを維持して滞在する時間（休眠タイマーをリセット）


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # Playwright 未導入でもジョブは落とさない
        print(f"[keepalive] playwright import failed: {e}")
        return 0

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            print(f"[keepalive] opening {APP_URL}")
            page.goto(APP_URL, wait_until="load", timeout=90_000)

            # スリープしていれば起床ボタンをクリックして復帰させる
            clicked = False
            for text in WAKE_TEXTS:
                try:
                    btn = page.get_by_text(text, exact=False)
                    if btn.count() > 0:
                        btn.first.click(timeout=5_000)
                        print(f"[keepalive] clicked wake-up button: {text!r}")
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                print("[keepalive] no wake-up button (app likely already awake)")

            # 起床直後は再ビルドで時間がかかるので長めに待ってから滞在する
            try:
                page.wait_for_load_state("networkidle", timeout=60_000)
            except Exception:
                pass
            page.wait_for_timeout(DWELL_MS)
            print("[keepalive] dwell complete; session kept alive")
            browser.close()
    except Exception as e:  # ネットワーク/タイムアウト等でも失敗にしない
        print(f"[keepalive] non-fatal error: {e}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
