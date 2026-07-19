FROM node:20-alpine AS frontend-build

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-alpine

ENV TZ=Pacific/Auckland
ENV PURERETA_ROOT=/app
ENV PORT=80

RUN apk add --no-cache tzdata \
    && ln -snf /usr/share/zoneinfo/${TZ} /etc/localtime \
    && echo ${TZ} > /etc/timezone

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ /app/server/
COPY data/migrations/ /app/_seed/migrations/
COPY data/seed_empty_spool_weights.json /app/_seed/seed_empty_spool_weights.json
COPY --from=frontend-build /build/dist/ /app/dist/

RUN chmod +x /app/server/entrypoint.sh

EXPOSE 80

ENTRYPOINT ["/app/server/entrypoint.sh"]
