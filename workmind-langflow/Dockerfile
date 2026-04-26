# WorkMind — Langflow Headless Runtime
# Uses official Langflow image with custom flow pre-loaded.
# NOT exposed to end-users; called internally by workmind-api only.

FROM langflowai/langflow:1.1.1

# Pre-copy flows into the container
# Flows are also mounted as a volume in docker-compose.yml for live updates
COPY flows/ /app/flows/

# Langflow config via env vars (set in docker-compose.yml):
#   LANGFLOW_DATABASE_URL
#   LANGFLOW_AUTO_LOGIN=false
#   LANGFLOW_SECRET_KEY
#   LANGFLOW_WORKERS=2
EXPOSE 7860

CMD ["langflow", "run", "--host", "0.0.0.0", "--port", "7860"]
