FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic

RUN python -m pip install --upgrade pip && \
    python -m pip install . && \
    chown -R app:app /app

USER app
EXPOSE 8000

CMD ["uvicorn", "career_agent_api.main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
