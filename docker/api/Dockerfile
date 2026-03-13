FROM duckclaw-base:latest

WORKDIR /app

# Copy shared and agents logic
COPY packages/shared /app/packages/shared
COPY packages/agents /app/packages/agents
COPY services/api-gateway /app/services/api-gateway

# Install local packages
RUN pip install /app/packages/shared
RUN pip install /app/packages/agents

WORKDIR /app/services/api-gateway
RUN pip install -r requirements.txt || true

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
