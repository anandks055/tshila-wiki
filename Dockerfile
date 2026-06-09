FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api_server.py .

ENV STATIC_DIR=/data/wiki-articles
ENV PORT=7171
ENV ENABLE_REGENERATE=false

EXPOSE 7171

CMD ["sh", "-c", "uvicorn api_server:app --host 0.0.0.0 --port ${PORT} --workers 1"]
