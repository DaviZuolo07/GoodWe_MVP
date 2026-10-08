# Painel do gestor como SITE ESTÁTICO de produção, igual ao que a Vercel serve.
# Usado pelo docker-compose.yml da raiz. Este app não tem chave nenhuma.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG VITE_ADMIN_API_URL
ENV VITE_ADMIN_API_URL=${VITE_ADMIN_API_URL}
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
