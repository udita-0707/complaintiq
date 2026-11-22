# ComplaintIQ reviewer UI on Hugging Face Spaces (Docker SDK). Built from the staging
# directory that `scripts/build_space.py ui` creates. Talks to the API at CIQ_API_URL
# (set it as a Space variable). Stdlib + Streamlit only; stores no complaint text.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 1000 user
WORKDIR /app
RUN pip install "streamlit==1.66.1"

COPY --chown=user:user app.py ciq_client.py ./
COPY --chown=user:user .streamlit ./.streamlit

USER user
ENV HOME=/home/user
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health')"

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", \
     "--browser.gatherUsageStats=false"]
