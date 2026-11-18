FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglu1-mesa libxrender1 libxext6 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV STORAGE_DIR=/data/files
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
