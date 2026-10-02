FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8081

RUN useradd --create-home --shell /usr/sbin/nologin app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app app
COPY alembic alembic
COPY alembic.ini .
COPY templates templates
COPY static static

RUN mkdir -p /app/data/resumes && chown -R app:app /app
USER app

EXPOSE 8081
CMD alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
