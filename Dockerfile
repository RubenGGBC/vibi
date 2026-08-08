FROM node:22-bookworm-slim AS frontend-build

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build


FROM python:3.12-slim AS runtime

# git para trabajar con repos; nodejs y Claude Code para poder iniciar
# sesión con una cuenta Pro/Max además de usar una API key.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates nodejs npm \
    && npm install -g @anthropic-ai/claude-code \
    && rm -rf /var/lib/apt/lists/* /root/.npm

# La CLI de Antigravity (`agy`), motor de chat alternativo. Es un binario Go
# único: no necesita runtime, solo el instalador oficial. Se mueve a
# /usr/local/bin para que esté en el PATH del proceso de uvicorn, que no hereda
# el ~/.local/bin donde el script lo deja.
RUN curl -fsSL https://antigravity.google/cli/install.sh | bash \
    && mv /root/.local/bin/agy /usr/local/bin/agy \
    && agy --help > /dev/null 2>&1 || true

WORKDIR /srv/morgana
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY --from=frontend-build /build/dist ./frontend/dist

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

