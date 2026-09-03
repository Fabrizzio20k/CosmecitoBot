FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY cosmecito_db ./cosmecito_db
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
COPY api/app.py .

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
