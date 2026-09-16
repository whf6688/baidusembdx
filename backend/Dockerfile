FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "playwright>=1.49,<2" \
    && playwright install --with-deps chromium
COPY packages/baidu_platform_core /app/packages/baidu_platform_core
COPY backend /app/backend
RUN pip install --no-cache-dir /app/packages/baidu_platform_core /app/backend
WORKDIR /app/backend
EXPOSE 8000
