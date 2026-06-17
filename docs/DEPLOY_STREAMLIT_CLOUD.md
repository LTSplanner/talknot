# TalKnot を Streamlit Community Cloud に公開する手順（無料・スマホ対応）

無料・カード不要で、社内メンバーがスマホからも使えるよう公開する手順です。
コードは GitHub の **`LTSplanner/talknot`（非公開）** に置いてあります。

> 秘密情報（APIキー等）の実値はこのファイルには書きません。チャットで別途渡した
> 「Secrets 貼り付け用テキスト」を使ってください。

---

## 前提（準備済み）
- ✅ GitHub 非公開リポジトリ `LTSplanner/talknot`
- ✅ Streamlit Secrets 対応（`app.py` が st.secrets を読む）
- ✅ スマホ最適化UI

## この段階で使わないもの（後日でOK）
- サービスアカウント鍵（代理ドライブ機能）：ドメイン全体委任(DWD)が承認されてから追加
- 永続保存(GCS)：無料枠では使わない（再起動で評価履歴がリセットされる点に注意）

---

## 手順

### 1. 公開URL（サブドメイン）を決める
Streamlit のURLは `https://<好きな名前>.streamlit.app`。
本手順では例として **`talknot-lts`** を使います（URL: `https://talknot-lts.streamlit.app`）。
※ 既に使われていたら別名にし、以降の URL もそれに合わせて読み替え。

### 2. Streamlit Community Cloud にサインイン
1. https://share.streamlit.io を開く
2. 「**Continue with GitHub**」→ GitHub（LTSplanner）で認証
3. 初回は talknot リポジトリへのアクセス許可を求められたら許可

### 3. 新しいアプリを作成
1. 「**Create app**」→「Deploy a public app from GitHub」系の選択
2. 入力：
   - **Repository**：`LTSplanner/talknot`
   - **Branch**：`main`
   - **Main file path**：`app.py`
   - **App URL（サブドメイン）**：`talknot-lts`（手順1で決めた名前）

### 4. Secrets を貼り付ける（重要）
1. 作成画面の「**Advanced settings**」→「**Secrets**」を開く
2. チャットで渡した **Secrets 貼り付け用テキスト**（TOML形式）をそのまま貼り付け
3. 保存

### 5. デプロイ
「**Deploy**」を押す → 数分でビルド完了 → アプリが開く。
（この時点では Google ログインはまだ通りません。次の手順6で有効化します）

### 6. Google ログインを有効化（OAuth リダイレクト登録）
1. https://console.cloud.google.com/apis/credentials を開く（プロジェクト `eigyou-ro-pure`）
2. OAuth 2.0 クライアントID（`908284664382-...`）を開く
3. 「**承認済みのリダイレクト URI**」に公開URLを追加（末尾スラッシュ無し）：
   ```
   https://talknot-lts.streamlit.app
   ```
4. 保存（反映に数分かかることあり）

### 7. スマホで確認
スマホのブラウザで `https://talknot-lts.streamlit.app` を開く →
「Googleでログイン」→ 社内アカウントでログイン → 評価タブが使えればOK。

---

## 更新のしかた
コードを直したら GitHub に push するだけで、Streamlit Cloud が自動で再デプロイします。
```bash
cd "/Users/kumadaharuki/クロードコード/TalKnot（トークノット）"
export PATH="$HOME/gh-cli/gh_2.95.0_macOS_arm64/bin:$PATH"
git add -A && git commit -m "変更内容" && git push
```

## 注意・補足
- **アクセス制御**：URLは誰でも開けますが、アプリ内のGoogleログインで
  `life-time-support.com` 限定のため社外の人は入れません。
- **評価履歴の保存**：無料構成では再起動でリセットされます。恒久保存が必要に
  なったら、無料DB（例：Firestore無料枠/Supabase）や Cloud Run + GCS への移行を検討。
- **代理ドライブ機能**：DWD 承認後に、サービスアカウント鍵を Secrets に追加すれば有効化できます。
