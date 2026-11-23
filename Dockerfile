FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

# Run as a non-root user: the agent writes files, so limit what the process can touch.
RUN useradd --create-home app && mkdir -p /app/var && chown app /app/var
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "engassist.api:app", "--host", "0.0.0.0", "--port", "8000"]
