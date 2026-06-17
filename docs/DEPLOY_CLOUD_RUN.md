# TalKnot を Cloud Run に公開する手順（スマホ対応）

社内メンバーがスマホからも使えるように、TalKnot を **Google Cloud Run** に常時稼働の
HTTPS URL で公開する手順です。GCPプロジェクトは既存の **`eigyou-ro-pure`** を使います。

> 用語：このページのコマンドは Mac のターミナルに貼り付けて実行します。
> Claude Code 上なら行頭に `! ` を付けて実行できます（例：`! gcloud auth login`）。

---

## 全体像

| 区分 | 内容 |
|---|---|
| A. 初回だけ | gcloud導入 → API有効化 → バケット作成 → シークレット登録 → 権限付与 |
| B. デプロイ | `bash scripts/deploy_cloud_run.sh` を実行（URLが出る） |
| C. ログイン設定 | 出たURLを OAuth リダイレクトに登録し、URLを設定して再デプロイ |
| D. 確認 | スマホでURLを開く |

---

## A. 初回セットアップ（1回だけ）

### A-1. gcloud SDK をインストール
Mac（Homebrew）の場合：
```bash
brew install --cask google-cloud-sdk
```
Homebrew が無ければ https://cloud.google.com/sdk/docs/install からインストール。

### A-2. ログイン＆プロジェクト設定
```bash
gcloud auth login
gcloud config set project eigyou-ro-pure
```

### A-3. 必要な API を有効化
```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com
```

### A-4. 永続化用の GCS バケットを作成
評価履歴・模範トークの保存先です（Cloud Run はファイルが消えるため必須）。
```bash
gcloud storage buckets create gs://talknot-data-eigyou-ro-pure \
  --location asia-northeast1 \
  --uniform-bucket-level-access
```

### A-5. シークレットを Secret Manager に登録
`.env` の値と、サービスアカウント鍵ファイルを登録します。
```bash
cd "/Users/kumadaharuki/クロードコード/TalKnot（トークノット）"

# .env から値を取り出して登録（GEMINI / OAuth）
grep '^GEMINI_API_KEY='     .env | cut -d= -f2- | tr -d '\n' | \
  gcloud secrets create GEMINI_API_KEY     --data-file=- --replication-policy=automatic
grep '^GOOGLE_CLIENT_ID='   .env | cut -d= -f2- | tr -d '\n' | \
  gcloud secrets create GOOGLE_CLIENT_ID   --data-file=- --replication-policy=automatic
grep '^GOOGLE_CLIENT_SECRET=' .env | cut -d= -f2- | tr -d '\n' | \
  gcloud secrets create GOOGLE_CLIENT_SECRET --data-file=- --replication-policy=automatic

# サービスアカウント鍵（DWD用）をファイルごと登録
gcloud secrets create talknot-sa-key \
  --data-file=secrets/eigyou-ro-pure-sa.json --replication-policy=automatic
```
> 値を更新したいときは `gcloud secrets versions add <名前> --data-file=-` で新版を追加。

### A-6. 実行用サービスアカウントに権限を付与
Cloud Run の実行アカウント（デフォルトの Compute SA）に、シークレット読み取りと
バケット読み書きを許可します。
```bash
PROJNUM=$(gcloud projects describe eigyou-ro-pure --format='value(projectNumber)')
RUNTIME_SA="${PROJNUM}-compute@developer.gserviceaccount.com"

# シークレット読み取り
for S in GEMINI_API_KEY GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET talknot-sa-key; do
  gcloud secrets add-iam-policy-binding "$S" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/secretmanager.secretAccessor"
done

# バケット読み書き
gcloud storage buckets add-iam-policy-binding gs://talknot-data-eigyou-ro-pure \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/storage.objectAdmin"
```

---

## B. デプロイ（初回 & 以降毎回）

```bash
cd "/Users/kumadaharuki/クロードコード/TalKnot（トークノット）"
bash scripts/deploy_cloud_run.sh
```
- ソースからクラウドでビルドされ、数分でデプロイされます（Docker不要）。
- 最後に **公開URL**（例：`https://talknot-xxxxxxxxxx.asia-northeast1.run.app`）が表示されます。
  → このURLを次のCで使います。

---

## C. Googleログインを有効にする（URL確定後）

### C-1. OAuth リダイレクトURIに公開URLを追加
1. https://console.cloud.google.com/apis/credentials を開く（プロジェクト `eigyou-ro-pure`）
2. OAuth 2.0 クライアントID（`908284664382-...`）を開く
3. 「**承認済みのリダイレクト URI**」に **Bで出た公開URL** を追加（末尾スラッシュ無し）
   - 例：`https://talknot-xxxxxxxxxx.asia-northeast1.run.app`
4. 保存（反映に数分かかることあり）

### C-2. アプリにも同じURLを教えて再デプロイ
```bash
OAUTH_REDIRECT_URI=https://talknot-xxxxxxxxxx.asia-northeast1.run.app \
  bash scripts/deploy_cloud_run.sh
```
（`https://...run.app` はBで出た実際のURLに置き換え）

---

## D. スマホで確認
スマホのブラウザで公開URLを開く →「Googleでログイン」→ 社内アカウントでログイン
→ 評価タブが使えればOK。

---

## 補足・注意

- **アクセス制御**：URL自体は誰でも開けますが、アプリ内のGoogleログインで
  `life-time-support.com` ドメインに限定しているため、社外の人は入れません。
- **代理ドライブ機能（8アカウント）**：先に進めている「ドメイン全体委任（DWD）」が
  完了していれば、Cloud Run 上でもそのまま代理アクセスできます（鍵はSecret Manager
  経由でマウント）。未完了の場合、その機能だけ使えません（他機能は動作します）。
- **費用**：Cloud Run は使った分だけ（アイドル時はほぼ無料枠内）。GCS もごく少額。
- **更新**：コードを直したら `bash scripts/deploy_cloud_run.sh` を再実行するだけ。
