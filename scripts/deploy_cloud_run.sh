#!/usr/bin/env bash
# TalKnot を Google Cloud Run にデプロイする。
#
# 事前準備（初回のみ）は docs/DEPLOY_CLOUD_RUN.md を参照。
# このスクリプトは「2回目以降の再デプロイ」も含め、毎回これを実行すればOK。
#
#   bash scripts/deploy_cloud_run.sh
#   # 公開URL確定後は OAUTH_REDIRECT_URI を渡して再実行：
#   OAUTH_REDIRECT_URI=https://xxx.run.app bash scripts/deploy_cloud_run.sh
#
set -euo pipefail

# === 設定（必要に応じて変更）======================================
PROJECT="eigyou-ro-pure"                 # GCP プロジェクト
REGION="asia-northeast1"                 # 東京リージョン
SERVICE="talknot"                        # Cloud Run サービス名
BUCKET="talknot-data-${PROJECT}"         # 永続化用 GCS バケット
SA_SECRET="talknot-sa-key"               # Secret Manager 上のSA鍵の名前
# ===================================================================

cd "$(dirname "$0")/.."

echo "▶ プロジェクト: ${PROJECT} / リージョン: ${REGION} / サービス: ${SERVICE}"
gcloud config set project "${PROJECT}" >/dev/null

# 非機密の環境変数を YAML に書き出す（値にカンマや @ を含むため、
# --set-env-vars の区切り問題を避けて --env-vars-file で渡すのが確実）。
ENV_FILE="$(mktemp -t talknot-env.XXXXXX.yaml)"
trap 'rm -f "${ENV_FILE}"' EXIT
{
  echo "ALLOWED_DOMAINS: \"life-time-support.com\""
  echo "ADMIN_EMAILS: \"planner@life-time-support.com,hkumada@life-time-support.com\""
  echo "REFERENCE_ACCOUNTS: \"kkyoya@life-time-support.com,hkumada@life-time-support.com\""
  echo "GEMINI_MODEL: \"gemini-2.5-flash\""
  echo "GCS_BUCKET: \"${BUCKET}\""
  echo "GOOGLE_SERVICE_ACCOUNT_FILE: \"/secrets/sa/key.json\""
  if [[ -n "${OAUTH_REDIRECT_URI:-}" ]]; then
    echo "OAUTH_REDIRECT_URI: \"${OAUTH_REDIRECT_URI}\""
    echo "▶ OAUTH_REDIRECT_URI=${OAUTH_REDIRECT_URI} を設定します" >&2
  else
    echo "⚠ OAUTH_REDIRECT_URI 未指定。初回はこのままデプロイ→URL確定後に再実行してください。" >&2
  fi
} > "${ENV_FILE}"

# 機密（Secret Manager 参照）。GEMINI_API_KEY 等は env として、SA鍵はファイルとしてマウント。
SECRETS="GEMINI_API_KEY=GEMINI_API_KEY:latest"
SECRETS="${SECRETS},GOOGLE_CLIENT_ID=GOOGLE_CLIENT_ID:latest"
SECRETS="${SECRETS},GOOGLE_CLIENT_SECRET=GOOGLE_CLIENT_SECRET:latest"
SECRETS="${SECRETS},/secrets/sa/key.json=${SA_SECRET}:latest"

gcloud run deploy "${SERVICE}" \
  --source . \
  --region "${REGION}" \
  --allow-unauthenticated \
  --memory 1Gi \
  --timeout 900 \
  --env-vars-file "${ENV_FILE}" \
  --set-secrets "${SECRETS}"

echo
echo "✅ デプロイ完了。公開URL:"
gcloud run services describe "${SERVICE}" --region "${REGION}" \
  --format 'value(status.url)'
