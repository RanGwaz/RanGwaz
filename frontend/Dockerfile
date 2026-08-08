FROM node:22-alpine AS build

WORKDIR /workspace
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE=/api
ARG VITE_MEDIA_UPLOAD_ENABLED=false
ENV VITE_API_BASE=${VITE_API_BASE}
ENV VITE_MEDIA_UPLOAD_ENABLED=${VITE_MEDIA_UPLOAD_ENABLED}
RUN npm run build

FROM nginx:1.27-alpine

ARG VIBELO_GIT_REVISION=unknown
LABEL org.opencontainers.image.source="https://github.com/RanGwaz/RanGwaz" \
      org.opencontainers.image.revision="${VIBELO_GIT_REVISION}" \
      org.opencontainers.image.title="Vibelo frontend"

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/dist /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD wget -q -O - http://127.0.0.1/healthz | grep -q ok || exit 1
