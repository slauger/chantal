# syntax=docker/dockerfile:1

# Build stage
FROM registry.access.redhat.com/ubi9/ubi:latest AS builder

# Install Python 3.11 and build dependencies
RUN dnf install -y \
    python3.11 \
    python3.11-pip \
    python3.11-devel \
    gcc \
    postgresql-devel \
    && dnf clean all

# Create virtual environment
RUN python3.11 -m venv /opt/venv

# Enable virtual environment
ENV PATH="/opt/venv/bin:$PATH"

# Copy project files
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install chantal and dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir .

# Runtime stage
FROM registry.access.redhat.com/ubi9/ubi-minimal:latest

# Install runtime dependencies
RUN microdnf install -y \
    python3.11 \
    libpq \
    shadow-utils \
    && microdnf clean all

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Enable virtual environment
ENV PATH="/opt/venv/bin:$PATH"

# Create chantal user and directories
RUN useradd -r -u 1000 -d /var/lib/chantal -s /sbin/nologin chantal && \
    mkdir -p /etc/chantal/conf.d /var/lib/chantal /var/www/repos && \
    chown -R chantal:chantal /etc/chantal /var/lib/chantal /var/www/repos

# Set working directory
WORKDIR /var/lib/chantal

# Switch to non-root user
USER chantal

# Define volumes
VOLUME ["/etc/chantal", "/var/lib/chantal", "/var/www/repos"]

# Set environment variables
ENV CHANTAL_CONFIG=/etc/chantal/config.yaml \
    PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD chantal --version || exit 1

# Default command
ENTRYPOINT ["chantal"]
CMD ["--help"]
