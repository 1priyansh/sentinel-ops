FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn httpx prometheus-client && useradd -m app
ARG SERVICE
ENV SERVICE=${SERVICE}
COPY common.py .
COPY ${SERVICE}/app.py .
USER app
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
