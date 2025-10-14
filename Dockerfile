FROM debian:bookworm-slim
ARG TARGETARCH
ARG TARGETVARIANT

# Install openWakeWord
WORKDIR /usr/src

COPY ./ ./
RUN \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
    \
    && python3 -m venv .venv \
    && .venv/bin/pip3 install --no-cache-dir -U \
        setuptools \
        wheel \
    && .venv/bin/pip3 install --no-cache-dir \
        --extra-index-url https://www.piwheels.org/simple \
        -e . \
    \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 10400

ENTRYPOINT ["bash", "docker_run.sh"]
