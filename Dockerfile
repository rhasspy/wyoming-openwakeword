FROM python:3.11.11-slim


COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --compile-bytecode

ADD . /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --compile-bytecode

EXPOSE 10400
