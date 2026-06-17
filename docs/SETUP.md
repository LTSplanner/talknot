# TalKnot セットアップ手順

実データで動画解析と Google ドライブ連携を動かすために必要な設定をまとめます。
所要：おおよそ 15〜20 分。

## 0. 前提

```bash
cp .env.example .env          # 設定ファイルを用意
pip install -r requirements.txt
```

以降、取得した値を `.env` に書き込みます。

---

## 1. Gemini API キー（動画解析に必須）

1. [Google AI Studio](https://aistudio.google.com/apikey) を開く
2. 「Create API key」でキーを発行
3. `.env` に設定：
   ```
   GEMINI_API_KEY=（発行したキー）
   GEMINI_MODEL=gemini-2.5-flash
   ```

> 動画解析は Files API を使うため、無料枠では容量・レート制限があります。
> 社内全社員で使う場合は有料プラン（課金有効化）を推奨します。

確認：
```bash
python3 scripts/check_setup.py        # 接続テストまで実行
python3 scripts/analyze_video.py 動画ファイル.mp4   # 解析だけ試す
```

---

## 2. Google OAuth（ログイン＋ドライブ連携に必須）

### 2-1. GCP プロジェクトと API 有効化
1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成（または選択）
2. 「APIとサービス」→「ライブラリ」で **Google Drive API** を有効化

### 2-2. OAuth 同意画面
1. 「APIとサービス」→「OAuth 同意画面」
2. User Type は **内部（Internal）** を選択（自社 Workspace 限定にできる）
3. アプリ名・サポートメールを入力
4. スコープに以下を追加：
   - `.../auth/userinfo.email`
   - `.../auth/userinfo.profile`
   - `openid`
   - `.../auth/drive.readonly`

### 2-3. OAuth クライアント ID
1. 「APIとサービス」→「認証情報」→「認証情報を作成」→「OAuth クライアント ID」
2. 種類：**ウェブアプリケーション**
3. **承認済みのリダイレクト URI** に追加：
   - ローカル: `http://localhost:8501`
   - 本番: 公開URL（例 `https://talknot.example.com`）
4. 発行された **クライアント ID / シークレット** を `.env` に：
   ```
   GOOGLE_CLIENT_ID=（クライアントID）
   GOOGLE_CLIENT_SECRET=（シークレット）
   OAUTH_REDIRECT_URI=http://localhost:8501
   ```

---

## 3. アクセス制御

```
ALLOWED_DOMAINS=yourcompany.com        # ログインを許可するドメイン（カンマ区切りで複数可）
ADMIN_EMAILS=admin@yourcompany.com     # 模範トークを登録できる管理者（カンマ区切り）
```

---

## 4. 起動

```bash
python3 scripts/check_setup.py   # 設定の最終確認
streamlit run app.py             # http://localhost:8501
```

- `GOOGLE_CLIENT_*` が未設定だと **デモログイン** にフォールバックします（Drive連携は使えません）。
- Meet の録画は通常 `Meet Recordings` フォルダに保存されます。共有ドライブにも対応しています。
