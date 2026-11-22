# ComplaintIQ API on Hugging Face Spaces (Docker SDK). Built from the staging directory that
# scripts/build_space.py creates (it contains src/, configs/ and the frozen model under
# models/). Never built from the GitHub repo root: models/ is not in git.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    COMPLAINTIQ_ROOT=/app \
    COMPLAINTIQ_CONFIG_DIR=/app/configs

# Spaces run the container as uid 1000.
RUN useradd --create-home --uid 1000 user
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[serve]"

COPY configs ./configs
COPY models ./models
RUN mkdir -p /app/runtime && chown user:user /app/runtime

USER user
ENV HOME=/home/user
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=3s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/health')"

# --proxy-headers: the client IP comes from the Spaces proxy (used by the rate limit).
CMD ["uvicorn", "complaintiq.serving.app:app", "--host", "0.0.0.0", "--port", "7860", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
