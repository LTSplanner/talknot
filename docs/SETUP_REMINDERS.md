# ロープレ習慣化リマインド 設定手順（管理者向け）

KNOTE に、ロープレを毎日の習慣にするための2つの仕組みを追加しました。

1. **カレンダー枠固定** … 各対象者のカレンダーに「KNOTEロープレ（5分）」を
   平日13:00 の繰り返し予定として自動で入れる。
2. **未実施リマインド** … 平日12:00 時点で午前中にロープレ未実施の人へ、Google Chat の
   個人DMで前向きに声かけする。

> ⚠️ この2つは **Google Workspace 管理者の設定** が必要です。設定が無い間は、
> スクリプト・ワークフローは何も送らず静かに終了します（CI を赤くしません）。

---

## この手順書を「管理者のPCのClaude Code」に渡す場合

そのまま渡してOKです。作業は2種類に分かれます。

**🧑 人がブラウザで行う（Claude Code では実行できない・GUI操作）**
- Google 管理コンソールでの「ドメイン全体の委任」スコープ追加（→ C）
- Google Chat API の「構成（アプリ設定）」と組織公開（→ A-2, A-5）

これらは `admin.google.com` / Google Chat の GUI 操作で、CLI/API では実質行えません。

**🤖 Claude Code が代行できる（CLI で実行。`<PROJECT>` は例: `eigyou-ro-pure`）**
```bash
# 1) 必要な API を有効化
gcloud services enable chat.googleapis.com admin.googleapis.com \
  calendar-json.googleapis.com --project=<PROJECT>

# 2) Chat 用の“最小権限”専用サービスアカウントと鍵を作る（強力なDWD鍵は流用しない）
gcloud iam service-accounts create knote-chat --project=<PROJECT> \
  --display-name="KNOTE Chat Reminder"
gcloud iam service-accounts keys create knote-chat.json \
  --iam-account=knote-chat@<PROJECT>.iam.gserviceaccount.com
#   → このSAの「クライアントID」を、🧑の委任（Cと同手順）に chat.bot と
#     admin.directory.user.readonly のスコープで登録してもらう

# 3) GitHub Secrets を登録（リポジトリ LTSplanner/talknot）
gh secret set KNOWLEDGE_SHEET_ID --body "<評価履歴シートID>"
gh secret set KNOWLEDGE_SA_JSON  < knowledge-sa.json
#   個人DM経路:
gh secret set CHAT_SA_JSON        < knote-chat.json
gh secret set CHAT_ADMIN_SUBJECT  --body "<Directoryを読める管理者メール>"

# 4) カレンダー枠作成・リマインドの動作確認（送らない/書かない）
export GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/dwd-sa.json
python scripts/setup_roleplay_calendar.py --dry-run     # 対象と内容を表示
export KNOWLEDGE_SHEET_ID=... KNOWLEDGE_SA_FILE=/path/to/knowledge-sa.json
python scripts/send_roleplay_reminders.py --dry-run     # 未実施者と本文を表示
```

**渡し方のコツ**：管理者のClaude Code にこのファイルを開かせ、
「🤖の項目をCLIで実行し、🧑の項目は必要な操作を私（管理者）に指示して」と伝えると、
自動化できる所は代行し、GUIが要る所は手順を案内してくれます。

---

## ✅ 今回の方針：個別DM経路（管理者チェックリスト）

各プランナーの Google Chat に **bot から個別DM** で、
「午前中ロープレ未実施の人へ・平日12:00・休みの人は除外」してリマインドします。上から順に。

**① GCPプロジェクト `eigyou-ro-pure`（オーナー権限：例 hkumada@）**
- [ ] Chat API / Admin SDK API を有効化（Calendar API は有効化済み）
- [ ] Chat用の**最小権限SA `knote-chat`** を作成し、鍵(JSON)を発行
      （↑「🤖 Claude Codeが代行できる」のコマンドでOK）

**② Google Workspace 管理者（admin.google.com）※ここがWorkspace管理者必須**
- [ ] ドメイン全体の委任に **`knote-chat` SAのクライアントID** を登録＋スコープ許可（→ C）：
      `https://www.googleapis.com/auth/chat.bot`
      `https://www.googleapis.com/auth/admin.directory.user.readonly`
- [ ] **既存の録画用DWD SA** に カレンダーのスコープを追加（枠作成＋休み判定用）（→ C）：
      `https://www.googleapis.com/auth/calendar.events`
      `https://www.googleapis.com/auth/calendar.readonly`
- [ ] **Google Chat API →「構成」**でアプリ作成（→ A）：アプリ名/アバター、
      **「1対1メッセージ」を有効**、**組織内に公開**、上の `knote-chat` SAを紐付け。
      組織ポリシーで **botからのDMを許可**。

**③ GitHub Secrets（リポジトリ `LTSplanner/talknot` → Settings → Secrets → Actions）**
- [ ] `CHAT_SA_JSON` … `knote-chat` の鍵JSON
- [ ] `CHAT_ADMIN_SUBJECT` … Directoryを読める管理者メール（例 `hkumada@life-time-support.com`）
- [ ] `CALENDAR_SA_JSON` … 録画用DWD SAの鍵JSON（枠作成＋休み判定用）
- [ ]（`KNOWLEDGE_SHEET_ID` / `KNOWLEDGE_SA_JSON` は登録済み）

**④ テスト**：Actions → `roleplay-reminder` → **Run workflow** で手動実行。以降は平日12:00に自動送信。
カレンダー枠は `python scripts/setup_roleplay_calendar.py`（まず `--dry-run`）で各人に作成。
個別DMの準備状況は、送信せず次のコマンドで8名分を一覧確認できます。

```bash
PYTHONPATH=. python scripts/check_chat_dm_readiness.py
```

---

## 全体像（どの鍵が何に使われるか）

| 用途 | 認証 | スコープ | 使う env |
| --- | --- | --- | --- |
| カレンダー枠作成 | DWD SA（各人を impersonate） | `calendar.events` | `GOOGLE_SERVICE_ACCOUNT_FILE` or `CALENDAR_SA_JSON` |
| 個人DM | Chat アプリSA + Directory DWD | `chat.bot` / `admin.directory.user.readonly` | `CHAT_SA_JSON`/`CHAT_SA_FILE`, `CHAT_ADMIN_SUBJECT` |
| 午前中実施の判定 | 知識SA（読み取り） | `spreadsheets` | `KNOWLEDGE_SHEET_ID`, `KNOWLEDGE_SA_JSON`/`KNOWLEDGE_SA_FILE` |
| 休みスキップ（任意） | DWD SA（各人を impersonate） | `calendar.readonly` | `CALENDAR_SA_JSON` or `GOOGLE_SERVICE_ACCOUNT_FILE` |

> **セキュリティ注記**：Chat 用は **専用の最小権限 SA** を新規発行してください。録画/ドライブ用の
> 強力な DWD 鍵を流用しないこと。強力な鍵は Streamlit 側に置かず **GitHub Secrets のみ** に。
> 本リポジトリは public です。Secrets はフォークには渡りませんが、万一の漏洩に備えて
> **鍵ごとに権限を最小化** してください。秘密情報は一切コミットしないでください。

---

## A. Google Chat アプリ（ボット）の作成 ＝ 個人DM経路

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

> 管理者がプランナー用のグループまたは組織単位へChatアプリを一括インストールすると、
> 各プランナーとボットの1対1 DMが用意されます。このグループはアプリ配布先を指定する
> ためだけに使い、グループチャットへは投稿しません。
> 個人DMが未設定・未作成の場合、ロープレ通知はグループ投稿へ切り替えず送信を中止します。

## B. Webhookはロープレ通知に使用しない

ロープレ未実施は本人だけへ伝えるため、`CHAT_WEBHOOK_URL` が登録されていても使用しません。
個人DMが使えない場合は何も送らず、安全に終了します。

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
- 個人DMに必須：
  - `CHAT_SA_JSON` … Chatアプリ用SAの鍵JSON（最小権限の専用SA）
  - `CHAT_ADMIN_SUBJECT` … Directory API 用に impersonate する管理者メール
`CHAT_WEBHOOK_URL` はロープレ通知では使用しません。

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

`.github/workflows/roleplay-reminder.yml` が **平日12:00(JST)** に自動実行します
（cron `0 3 * * 1-5` = 03:00 UTC）。手動実行は Actions タブの
`roleplay-reminder` → `Run workflow`。

### 送信前の検証（ローカル・送らない）

```bash
export KNOWLEDGE_SHEET_ID=xxxx
export KNOWLEDGE_SA_FILE=/path/to/knowledge-sa.json   # または KNOWLEDGE_SA_JSON
python scripts/send_roleplay_reminders.py --dry-run
```

`--dry-run` は午前中未実施者と送信本文を表示するだけで、**一切送信しません**。
Chat の env が未設定なら、通常実行でも送信せず警告して終了します（exit 0）。
`--dry-run` では「未実施者 ／ うち休みでスキップ ／ 実際に送る人」も表示されます。

---

## F. 休みの人には送らない（休みスキップ・任意）

午前中ロープレ未実施の人でも、その日が**休み**ならリマインドは送りません。休みかどうかは
本人のカレンダーの**予定タイトル**から判定します（DWD SA でカレンダーを読み取り）。

### 判定ルール（タイトル語で判定）

- **送らない（スキップ）**：タイトルに次の**OFF語**を含む予定が1つでもある人。
  終日でも時間指定でも検出します（実運用では終日でなく `中谷OFF 09:00〜22:00` のように
  時間指定で入るため、**終日かどうかは問いません**）。
  - OFF語: `OFF`/`off`, `休み`, `お休み`, `有給`, `有休`, `休暇`, `全休`, `代休`,
    `振替休日`, `振休`, `夏季休暇`, `冬季休暇`, `年末年始`, `全社休業`, `会社休`,
    `リフレッシュ休暇`, `特別休暇`, `産休`, `育休`, `慶弔`
  - 会社休（`夏季休暇` など）も対象（終日/時間指定を問わず送らない）。
- **送らない（午前中に勤務しない）**：
  - `午前休` / `午前半休` / `AM半休` は正午リマインドの対象外です。
- **送る（午前中に勤務する）**：
  - `午後休` / `午後半休` / `PM半休` は午前勤務のため対象です。
  - `半休` / `時間休` / `半日` のように午前・午後を特定できない予定は、
    取りこぼし防止のため対象に残します。
  - **祝日は送る**（祝日判定は実装しておらず、cron が平日のみのためそのまま平日として送信）。
  - `事務DAY` / `MTG` / `私用中抜け` / `資料作成` などはOFF語でないので送ります
    （**中抜けは稼働扱い**＝部分中抜けでは休みにしません）。

> **前提**：本人が**カレンダーに「休み／有給／夏季休暇」等を入れていること**が必要です。
> 予定が入っていなければ休みと判定できず、通常どおりリマインドが届きます。

### 設定

- 休みチェックには DWD SA のカレンダー**読み取り**が要ります。鍵は
  `CALENDAR_SA_JSON`（鍵JSON文字列・Secrets 向け）または
  `GOOGLE_SERVICE_ACCOUNT_FILE`（鍵ファイルのパス・ローカル向け）から読みます。
  スコープは `https://www.googleapis.com/auth/calendar.readonly` を C と同手順で委任してください。
- **未設定でも動きます**：カレンダーSAが無い・取得に失敗した場合は休み判定をスキップし、
  **全員（未実施者）に送ります**（安全側。誤って全員無送信にはしません）。
- GitHub Actions で使うには Secret `CALENDAR_SA_JSON` を登録します
  （`.github/workflows/roleplay-reminder.yml` の env に設定済み。無ければ休み判定はスキップ）。

---

## G. 評価エラーの管理者通知（Google Chat 個人DM）

評価（商談/ロープレ）が失敗したとき、`ERROR_NOTIFY_EMAIL`（既定 `hkumada@life-time-support.com`）へ
Google Chat の**個人DM**で通知します（実施者・対象・エラー内容）。

- 送信には Chat の DM 設定（`CHAT_SA_JSON` + `CHAT_ADMIN_SUBJECT`）が必要です。
  これは **リマインドと違いアプリ(Streamlit)側で送る**ため、**Streamlit の Secrets にも**
  `CHAT_SA_JSON` / `CHAT_ADMIN_SUBJECT` を設定してください（GitHub Secretsとは別）。
- 未設定なら通知は**静かにスキップ**（評価処理は通常どおり継続）。
- Webhook(`CHAT_WEBHOOK_URL`)しか無い場合は、そのスペースへ素の本文で投稿します（DMではない）。
- 宛先を変えるには env `ERROR_NOTIFY_EMAIL` を設定。空にすると通知しません。
