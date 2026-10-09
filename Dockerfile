FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY static ./static
RUN useradd --create-home --uid 10001 lab && mkdir -p /srv/data && chown lab /srv/data
USER lab
# asyncio loop: ragas uses nest_asyncio, which cannot patch uvloop.
CMD ["sh", "-c", "exec uvicorn app.main:build --factory --host ${BIND_HOST:-127.0.0.1} --port ${PORT:-8030} --proxy-headers --loop asyncio"]
