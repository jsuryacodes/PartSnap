# PartSnap API on Render (or any Docker host). OpenCascade (CadQuery) needs the GL/X runtime libs.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libxrender1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV MOCK_MODE=1
CMD uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}
