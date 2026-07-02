FROM python:3.11-slim

ARG APP_VERSION=0.1.0-beta.2
ARG BUILD_SHA=development

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV APP_VERSION=$APP_VERSION
ENV BUILD_SHA=$BUILD_SHA

LABEL org.opencontainers.image.title="EasySales Backend" \
      org.opencontainers.image.version=$APP_VERSION \
      org.opencontainers.image.revision=$BUILD_SHA

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
