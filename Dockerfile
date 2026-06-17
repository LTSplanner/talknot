# TalKnot — Cloud Run 用イメージ
FROM python:3.12-slim

WORKDIR /app

# 依存だけ先に入れてレイヤキャッシュを効かせる
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリ本体（.dockerignore で .env / secrets/ / data/ は除外済み）
COPY . .

# Cloud Run は $PORT（既定 8080）でリクエストを送る
ENV PORT=8080
EXPOSE 8080

# shell 形式で $PORT を展開する
CMD streamlit run app.py \
    --server.port=${PORT} \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false
