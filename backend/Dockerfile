# PartSnap API as a Hugging Face Docker Space (CPU basic, free): listens on 7860, runs as uid 1000.
# The same image runs anywhere Docker does. Keys come from the host's secrets, never the image.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libxrender1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    MOCK_MODE=1 \
    DEV_FAKE_FAILURES=0 \
    FRONTEND_ORIGIN=https://partsnap-one.vercel.app \
    GENERATIONS_PER_HOUR=5 \
    DAILY_PAID_CALL_CAP=300 \
    CACHE_DIR=/tmp/partsnap/cache \
    OUT_DIR=/tmp/partsnap/out
WORKDIR /home/user/app
COPY --chown=user . .
EXPOSE 7860
# One worker: the per-IP rate limit and the daily-cap lock are in-process.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
