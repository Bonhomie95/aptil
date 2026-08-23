FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps (build tools for cryptography, libs for file parsing) + curl for
# the healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

# Copy the package metadata AND the package itself before installing: the
# editable install resolves `app*` at build time, so installing before `COPY . .`
# produced an install that referenced nothing.
COPY pyproject.toml README.md* ./
COPY app ./app
RUN uv pip install --system -e "."

COPY . .

# Drop privileges: nothing in the API needs root.
RUN useradd --create-home --uid 10001 aptil && chown -R aptil:aptil /app
USER aptil

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# Default command overridden by docker-compose per service (api / worker).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
