FROM node:22-alpine AS frontend-build

WORKDIR /build/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend ./
RUN npm run build

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY . .
COPY --from=frontend-build /build/frontend/dist ./frontend/dist

RUN pip install .

EXPOSE 8080

ENTRYPOINT ["vikhry"]
