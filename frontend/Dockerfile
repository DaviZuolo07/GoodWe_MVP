# App do morador como SITE ESTÁTICO de produção, igual ao que a Vercel serve.
# Usado pelo docker-compose.yml da raiz. As chaves do Supabase vêm do
# frontend/.env (só chave PUBLICÁVEL - ela vai para o navegador de todo jeito).
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Variável de ambiente ganha do .env no Vite: a API fica fixa no endereço do compose.
ARG VITE_API_URL
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
