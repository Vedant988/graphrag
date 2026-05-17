# syntax=docker/dockerfile:1
FROM node:23.7-slim AS builder
WORKDIR /app

RUN npm install -g pnpm

COPY package.json pnpm-lock.yaml .npmrc ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    PNPM_IGNORE_BUILD_SCRIPTS_ERR=1 pnpm install --no-frozen-lockfile || \
    pnpm install --no-frozen-lockfile --ignore-scripts

COPY . .
RUN pnpm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000
CMD ["sh", "-c", "sed -i \"s|listen 3000;|listen ${PORT:-3000};|g; s|__GRAPHRAG_API_URL__|${GRAPHRAG_API_URL:-http://graphrag:8000}|g\" /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
