FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY hermes_mcp_bridge ./hermes_mcp_bridge
RUN pip install --no-cache-dir .

# The container needs no privilege at all: no Docker socket, no agent volume.
# It only talks to the dashboard over HTTP.
RUN useradd --create-home --uid 10001 bridge
USER bridge

EXPOSE 8080
CMD ["python", "-m", "hermes_mcp_bridge"]
