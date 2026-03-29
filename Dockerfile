FROM python:3.11-slim

WORKDIR /app

COPY suit-finder/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install --with-deps chromium

COPY suit-finder/ ./

CMD sh -c "uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT:-8080}"
