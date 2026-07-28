# ロープレ習慣化リマインド 設定手順（管理者向け）

KNOTE に、ロープレを毎日の習慣にするための2つの仕組みを追加しました。

1. **カレンダー枠固定** … 各対象者のカレンダーに「KNOTEロープレ（5分）」を
   平日13:00 の繰り返し予定として自動で入れる。
2. **未実施リマインド** … 平日15:00 時点でその日ロープレ未実施の人へ、Google Chat の
   個人DM（または指定スペースへのまとめ投稿）で前向きに声かけする。

> ⚠️ この2つは **Google Workspace 管理者の設定** が必要です。設定が無い間は、
> スクリプト・ワークフローは何も送らず静かに終了します（CI を赤くしません）。

---

## 全体像（どの鍵が何に使われるか）

| 用途 | 認証 | スコープ | 使う env |
| --- | --- | --- | --- |
| カレンダー枠作成 | DWD SA（各人を impersonate） | `calendar.events` | `GOOGLE_SERVICE_ACCOUNT_FILE` or `CALENDAR_SA_JSON` |
| 個人DM（推奨） | Chat アプリSA + Directory DWD | `chat.bot` / `admin.directory.user.readonly` | `CHAT_SA_JSON`/`CHAT_SA_FILE`, `CHAT_ADMIN_SUBJECT` |
| DMの簡易代替 | Incoming Webhook | 不要 | `CHAT_WEBHOOK_URL` |
| 当日実施の判定 | 知識SA（読み取り） | `spreadsheets` | `KNOWLEDGE_SHEET_ID`, `KNOWLEDGE_SA_JSON`/`KNOWLEDGE_SA_FILE` |

> **セキュリティ注記**：Chat 用は **専用の最小権限 SA** を新規発行してください。録画/ドライブ用の
> 強力な DWD 鍵を流用しないこと。強力な鍵は Streamlit 側に置かず **GitHub Secrets のみ** に。
> 本リポジトリは public です。Secrets はフォークには渡りませんが、万一の漏洩に備えて
> **鍵ごとに権限を最小化** してください。秘密情報は一切コミットしないでください。

---

## A. Google Chat アプリ（ボット）の作成 ＝ 個人DM経路（推奨）

1. [Google Cloud Console](https://console.cloud.google.com/) の対象プロジェクトで
   「APIとサービス」→「ライブラリ」から **Google Chat API** と **Admin SDK API** を有効化。
2. 「Google Chat API」→「**構成（Configuration）**」でアプリを設定：
   - アプリ名／アバターURL／説明を入力
   - **機能**：「1対1のメッセージを受信する」等を有効化（DM を送るため）
   - **接続設定**：App Script/HTTP は不要（本アプリは API 直呼びのため）
   - **公開状態**：組織内に公開（org 内でのみDM可能に）
3. アプリに紐づく **サービスアカウントの鍵(JSON)** を発行（「IAMと管理」→「サービスアカウント」→
   対象SA →「キー」→「鍵を追加」→ JSON）。これが `CHAT_SA_JSON`（Secrets 向け文字列）。
4. **Directory API でメール→ユーザーID を解決**するため、この SA に
   ドメイン全体委任を追加（下記 C と同様の手順）。スコープ：
   ```
   https://www.googleapis.com/auth/admin.directory.user.readonly
   ```
   そして `CHAT_ADMIN_SUBJECT` に、Directory を読める **管理者のメール** を設定。
5. Chat 投稿自体はアプリ認証（`chat.bot`）で行います。組織のポリシーでボットからの
   DM を許可しておいてください。

> **難しければ、まずは Webhook で開始（下記 B）**。DM の org 設定が整ってから A に移行できます。
> 送信経路は env の有無で自動判定されます（DM 用 env があれば DM、無ければ Webhook）。

## B. かんたん代替：Chat スペース + Incoming Webhook

1. 通知用の Google Chat スペースを作成（対象者を招待）。
2. スペースの「アプリと統合」→「Webhook」→ 追加 → **Webhook URL** を発行。
3. その URL を `CHAT_WEBHOOK_URL`（GitHub Secrets）に設定。
4. この経路では個別DMではなく、**未実施者をまとめた1通**をスペースへ投稿します。

---

## C. DWD SA に `calendar.events` を委任（カレンダー枠用）

既存の録画用 DWD SA、または新規SAのクライアントIDに対して、管理コンソールで委任スコープを追加します。

1. [Google 管理コンソール](https://admin.google.com/) を超管理者で開く
2. 「**セキュリティ**」→「**アクセスとデータ管理**」→「**API の制御**」
3. 「**ドメイン全体の委任**」→「**新しく追加**」（既存クライアントIDなら編集）
4. **OAuth スコープ**に追加：
   ```
   https://www.googleapis.com/auth/calendar.events
   ```
5. 「承認」で保存（反映に数分かかることがあります）。

---

## D. GitHub Secrets 一覧

`Settings` → `Secrets and variables` → `Actions` に登録：

- `KNOWLEDGE_SHEET_ID` … 評価履歴シートのID（当日実施の判定に使用）
- `KNOWLEDGE_SA_JSON` … 評価履歴シートを読む知識SAの鍵JSON
- 個人DM経路を使う場合：
  - `CHAT_SA_JSON` … Chatアプリ用SAの鍵JSON（最小権限の専用SA）
  - `CHAT_ADMIN_SUBJECT` … Directory API 用に impersonate する管理者メール
- Webhook経路を使う場合：
  - `CHAT_WEBHOOK_URL` … 通知先スペースの Webhook URL

> DM 用 env と Webhook URL の両方があれば **DM が優先**されます。

---

## E. 実行方法

### カレンダー枠の作成（手動運用）

各対象者（`TARGET_ACCOUNTS`）のカレンダーへ、平日13:00・5分・毎週(月〜金)の予定を作成/更新します。
`extendedProperties.private.knote_roleplay=1` を冪等キーに使うため、**何度実行しても二重に増えません**。

```bash
export GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/dwd-sa.json   # または CALENDAR_SA_JSON
# まず内容確認（作成しない）
python scripts/setup_roleplay_calendar.py --dry-run
# 問題なければ実行
python scripts/setup_roleplay_calendar.py
```

- 時刻を変えたいとき：`export ROLEPLAY_SLOT_HHMM="13:30"`（既定 `13:00`）。

### 未実施リマインド（自動＝GitHub Actions）

`.github/workflows/roleplay-reminder.yml` が **平日15:00(JST)** に自動実行します
（cron `0 6 * * 1-5` = 06:00 UTC）。手動実行は Actions タブの
`roleplay-reminder` → `Run workflow`。

### 送信前の検証（ローカル・送らない）

```bash
export KNOWLEDGE_SHEET_ID=xxxx
export KNOWLEDGE_SA_FILE=/path/to/knowledge-sa.json   # または KNOWLEDGE_SA_JSON
python scripts/send_roleplay_reminders.py --dry-run
```

`--dry-run` は当日未実施者と送信本文を表示するだけで、**一切送信しません**。
Chat の env が未設定なら、通常実行でも送信せず警告して終了します（exit 0）。
