# KNOTE 個別DMリマインド：最後の2点の受け渡し手順（管理者 → planner@）

Chatの個別DMリマインドは、GCP/Workspace側の設定（Chat API・`knote-chat` SA・
ドメイン全体委任・Chatアプリ「KNOTEリマインド」・talknot-drive のカレンダー権限）が
**完了済み**です。残るは GitHub Secrets 2つの登録だけで、それは planner@（GitHubリポジトリ
`LTSplanner/talknot` のオーナー）が行います。

そのために、**管理者から planner@ へ次の2点**をお渡しください。

## 渡してほしい2点
1. **`knote-chat.json`**（Chat用サービスアカウントの鍵ファイル）
2. **`CHAT_ADMIN_SUBJECT` に使う管理者メール**（Directory解決の動作確認に使ったアカウント）

> ⚠️ 鍵は**本文に貼らない**。共有ドライブの限定共有など、安全な方法で渡してください。

---

## 【A】人が手で行う場合

### A-1. `knote-chat.json` を用意して渡す
- 作成時の `knote-chat.json` が手元にある → それを使う。
- 無い／紛失した → 新しい鍵を発行（Cloud Console）：
  1. [Google Cloud Console](https://console.cloud.google.com/) で対象プロジェクト **eigyou-ro-pure** を選択
  2. 「IAM と管理」→「サービス アカウント」→ `knote-chat@eigyou-ro-pure.iam.gserviceaccount.com`
  3. 「キー」タブ →「鍵を追加」→「新しい鍵を作成」→ **JSON** → ダウンロード
- 渡し方（安全に）：
  - 例）Google ドライブに置き、**planner@ だけ閲覧可**にして共有
  - ※チャット/メールの**本文に鍵の中身を貼らない**

### A-2. 管理者メールを伝える
- `CHAT_ADMIN_SUBJECT` は、Directory API（`admin.directory.user.readonly`）の
  **subject に使い、動作確認できた管理者アカウントのメール**です。
- 例：`ryouchiku@life-time-support.com` など。planner@ に「これを `CHAT_ADMIN_SUBJECT` に使って」と伝える。

---

## 【B】管理者の PC の Claude Code に渡して進める場合
（この節をそのまま管理者の Claude Code に開かせてOK）

前提：`gcloud` が eigyou-ro-pure を操作できる状態（s.kageyama@ に一時付与済みの
Service Account Key Admin 等）。gcloud 未ログインなら先に `gcloud auth login`。

```bash
# 1) Chat用SAの鍵を発行（すでに knote-chat.json があればスキップ）
gcloud iam service-accounts keys create knote-chat.json \
  --iam-account=knote-chat@eigyou-ro-pure.iam.gserviceaccount.com \
  --project=eigyou-ro-pure

# 2) 鍵の「中身」は画面表示・貼り付けしない。ファイル knote-chat.json を
#    planner@ に安全な方法（共有ドライブの限定共有 等）で渡す。

# 3) CHAT_ADMIN_SUBJECT に使う管理者メールを planner@ に伝える
#    （Directory解決を確認したアカウント。例 ryouchiku@life-time-support.com）
```

> GitHub Secrets の登録は **planner@（リポジトリオーナー）だけ**が可能です
> （`LTSplanner` は個人アカウントのため、共同編集者に Admin を付けられません）。
> よって管理者側の作業は「鍵ファイルとメールを渡す」までです。

---

## planner@ 側（受領後にやること）
`knote-chat.json` を受け取り、リポジトリの `secrets/` に置いてから：
```bash
gh secret set CHAT_SA_JSON < secrets/knote-chat.json
gh secret set CHAT_ADMIN_SUBJECT --body "もらった管理者メール"
```
（`CALENDAR_SA_JSON` は登録済み）

その後：
- 対象8名が Google Chat で bot **「KNOTEリマインド」を一度開く**（利用可反映は最大24h）
- 以降、**平日15:00 に自動で個別DMリマインド**（当日ロープレ未実施の人・休みの人は除外）

---

## 補足
- 作業完了後、s.kageyama@ に一時付与した GCP 3ロール（Service Usage / Service Account /
  Service Account Key Admin）は削除して問題ありません。
- うまく動かない場合の切り分け：`gh secret list` に `CHAT_SA_JSON`/`CHAT_ADMIN_SUBJECT`/
  `CALENDAR_SA_JSON` が並ぶか → Actions の `roleplay-reminder` を手動実行してログ確認。
