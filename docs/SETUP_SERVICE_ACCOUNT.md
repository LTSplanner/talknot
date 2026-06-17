# サービスアカウント＋ドメイン全体委任（DWD）設定手順

TalKnot が、各メンバー（営業）の Google ドライブにある Meet 録画を、本人のログイン
なしで代理アクセスするための設定です。**Google Workspace の超管理者（特権管理者）**
の操作が必要な箇所があります。

> この手順は社内の Workspace 管理者にそのまま渡せます。完了後、発行された JSON 鍵を
> アプリ運用者に渡し、`.env` の `GOOGLE_SERVICE_ACCOUNT_FILE` に設定します。

---

## A. GCP：サービスアカウントと鍵の作成（GCPプロジェクト編集者で可）

1. [Google Cloud Console](https://console.cloud.google.com/) で対象プロジェクトを開く
2. 「APIとサービス」→「ライブラリ」で **Google Drive API** を有効化（未なら）
3. 「IAMと管理」→「サービス アカウント」→「**サービス アカウントを作成**」
   - 名前例：`talknot-drive`
4. 作成したサービスアカウントを開き「**キー**」タブ →「鍵を追加」→「新しい鍵を作成」→ **JSON**
   - ダウンロードされた JSON ファイルを安全に保管（これが `GOOGLE_SERVICE_ACCOUNT_FILE`）
5. サービスアカウントの詳細画面で「**クライアント ID**」（数字の長いID）をメモ
   - 「詳細」→「一意のID（Unique ID / Client ID）」

---

## B. Admin Console：ドメイン全体委任の許可（**超管理者のみ**）

1. [Google 管理コンソール](https://admin.google.com/) を超管理者で開く
2. 「**セキュリティ**」→「**アクセスとデータ管理**」→「**API の制御**」
3. 「**ドメイン全体の委任**」→「**新しく追加**」
4. 次を入力：
   - **クライアント ID**：手順 A-5 でメモした数字のクライアントID
   - **OAuth スコープ**：以下を**カンマなしの1行 or 1つずつ**追加
     ```
     https://www.googleapis.com/auth/drive.readonly
     ```
5. 「承認」で保存

> 反映に数分かかることがあります。

---

## C. アプリ側の設定（運用者）

`.env` に鍵ファイルのパスを設定：

```
GOOGLE_SERVICE_ACCOUNT_FILE=/絶対パス/talknot-drive-xxxx.json
REFERENCE_ACCOUNTS=kkyoya@life-time-support.com,hkumada@life-time-support.com
# 対象メンバーを変える場合のみ（既定は settings.py の8名）
# TARGET_ACCOUNTS=a@example.com,b@example.com
```

確認スクリプト：

```bash
python3 scripts/check_drive_delegation.py
```

各メンバーのドライブに代理アクセスできるか（動画件数）を一覧表示します。
すべて 0 件やエラーの場合は B の委任設定（クライアントID / スコープ）を見直してください。

---

## セキュリティ注意

- JSON 鍵は**機密情報**。リポジトリにコミットしない（`.gitignore` 済み）。
- 委任スコープは **`drive.readonly`（読み取り専用）**に限定。書き込み・削除はできません。
- 対象を限定したい場合、Workspace 側で対象 OU を絞る運用も検討してください。
