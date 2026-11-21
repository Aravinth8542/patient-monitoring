FROM python:3.12-slim
WORKDIR /srv/app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN pip install --no-cache-dir --timeout 180 --retries 10 -r requirements.txt
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts
EXPOSE 8000
CMD ["python", "-m", "scripts.run_container_api"]
