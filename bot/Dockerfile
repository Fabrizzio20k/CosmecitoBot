FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY bot/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY cosmecito_db ./cosmecito_db
COPY bot/main.py .
COPY bot/cosmecito_bot ./cosmecito_bot

CMD ["python", "main.py"]
