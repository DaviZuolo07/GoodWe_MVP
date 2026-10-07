# =============================================================================
# Backend do ChargeOps - UMA imagem, DOIS serviços (ADR-023)
# =============================================================================
# Construir a partir da RAIZ do repositório (o requirements.txt mora lá):
#     docker build -f backend/Dockerfile -t chargeops-backend .
#
# API pública (app do morador + totem), porta 8000:
#     docker run --env-file backend/.env -e AMBIENTE=producao -p 8000:8000 chargeops-backend
# API administrativa (painel do gestor), porta 8001:
#     docker run --env-file backend/.env -e AMBIENTE=producao -e SERVICO=admin -p 8001:8001 chargeops-backend
#
# Nenhum segredo entra na imagem: tudo vem por variável de ambiente.
# =============================================================================
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AMBIENTE=producao \
    SERVICO=publico

WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY backend/ /app/
# Garantia extra: se um .env escapar do .dockerignore, não fica na imagem.
RUN rm -f /app/.env /app/.env.* && rm -rf /app/testes /app/evals /app/__pycache__

# Processo sem privilégio: o backend não precisa ser root para nada.
RUN useradd --system --no-create-home --uid 10001 chargeops
USER chargeops

EXPOSE 8000 8001
# UM processo por serviço, de propósito: o laço do simulador e os limitadores
# de tentativa vivem na memória do processo (ver seguranca.py). Não use
# --workers > 1 na API pública.
# --proxy-headers fica DESLIGADO: quem lê o IP real é o próprio backend, com
# PROXIES_CONFIAVEIS (aceitar X-Forwarded-For de qualquer um permitiria forjar IP).
CMD ["sh", "-c", "if [ \"$SERVICO\" = admin ]; then exec uvicorn main_admin:app --host 0.0.0.0 --port ${PORT:-8001} --no-proxy-headers --no-server-header; else exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --no-proxy-headers --no-server-header; fi"]
