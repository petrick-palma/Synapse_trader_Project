FROM python:3.11-slim

# Variáveis de ambiente
ENV PYTHONUNBUFFERED=1
ENV EXECUTION_ENVIRONMENT=GCP
ENV PORT=8080

# Instalar dependências de sistema
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc g++ make cmake libblas-dev liblapack-dev gnupg && \
    rm -rf /var/lib/apt/lists/*

# Diretório de trabalho
WORKDIR /app

# Copiar e instalar dependências
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copiar aplicação
COPY . .

# Expor porta
EXPOSE 8080

# Comando CORRETO para FastAPI em produção
CMD ["uvicorn", "run_api:app", "--host", "0.0.0.0", "--port", "8080"]   