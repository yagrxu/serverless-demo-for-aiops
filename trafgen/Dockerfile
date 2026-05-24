FROM python:3.12-slim AS builder

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy everything needed for the build
COPY pyproject.toml ./
COPY trafgen/ ./trafgen/
COPY profiles/ ./profiles/

# Install the package (no dev deps)
RUN uv pip install --system --no-cache .

# Production image
FROM python:3.12-slim

WORKDIR /app

# Copy installed packages and entrypoint from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/trafgen /usr/local/bin/trafgen
COPY --from=builder /usr/local/bin/opentelemetry-instrument /usr/local/bin/opentelemetry-instrument
COPY --from=builder /app/trafgen ./trafgen
COPY --from=builder /app/profiles ./profiles

# OTel auto-instrumentation wraps the trafgen CLI so outgoing HTTP calls
# produce client spans that appear in the Service Map.
ENTRYPOINT ["opentelemetry-instrument", "trafgen"]
CMD ["run", "--target", "cloud", "--profile", "/app/profiles/baseline.yaml", "--rps", "0.5", "--duration", "55m"]
