FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY hermes_mcp_bridge ./hermes_mcp_bridge
RUN pip install --no-cache-dir .

# Le conteneur n'a besoin d'aucun privilège : ni socket Docker, ni volume de
# l'agent. Il ne parle au dashboard que par HTTP.
RUN useradd --create-home --uid 10001 pont
USER pont

EXPOSE 8080
CMD ["python", "-m", "hermes_mcp_bridge"]
