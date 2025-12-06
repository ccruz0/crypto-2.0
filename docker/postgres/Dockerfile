# ---------- PostgreSQL Hardened ----------

FROM postgres:15-alpine

# Switch to root for setup
USER root

# Update packages and remove build caches
RUN apk update && \
    apk upgrade --no-cache && \
    apk add --no-cache bash tzdata curl && \
    rm -rf /var/cache/apk/*

# Set timezone (optional, can be overridden via environment)
ENV TZ=UTC

# Configure secure defaults (these can be overridden via environment variables)
ENV POSTGRES_USER=trader
ENV POSTGRES_PASSWORD=traderpass
ENV POSTGRES_DB=atp

# Create mount point for persistent data
RUN mkdir -p /var/lib/postgresql/data && chown -R postgres:postgres /var/lib/postgresql

VOLUME ["/var/lib/postgresql/data"]

# Switch back to postgres user
USER postgres

# Expose PostgreSQL default port
EXPOSE 5432

# Healthcheck for container monitoring
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD pg_isready -U $POSTGRES_USER || exit 1

CMD ["postgres"]

