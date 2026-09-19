FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 ripster
COPY pyproject.toml ./
COPY ripster_scanner ./ripster_scanner
COPY backend ./backend
COPY scanner ./scanner
COPY research ./research
COPY discovery ./discovery
COPY strategy_lab ./strategy_lab
RUN pip install '.[dashboard,test]'
COPY alembic.ini README.md ./
COPY migrations ./migrations
COPY config ./config
COPY tests ./tests
COPY scanner.py ./
RUN mkdir -p /app/data/uploads && chown -R ripster:ripster /app/data
USER ripster
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "backend.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
