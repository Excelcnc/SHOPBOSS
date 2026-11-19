# Single image: web app + API + worker + poller (used by Render, see render.yaml).
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglu1-mesa libxrender1 libxext6 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
COPY --from=web /web/dist /app/static
ENV STATIC_DIR=/app/static STORAGE_DIR=/data/files PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["./start.sh"]
