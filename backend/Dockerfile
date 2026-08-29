ARG PYTHON_IMAGE=python:3.12-slim-bookworm
FROM ${PYTHON_IMAGE}

ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${APP_GID}" coding-agent \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home --shell /bin/sh coding-agent

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY src ./src
COPY alembic ./alembic
COPY docs/evaluation-results ./evaluation-results

# 使用可编辑安装保留 /app/src 路径，使现有 Alembic 配置定位逻辑在镜像中保持一致。
RUN python -m pip install --no-cache-dir -e ".[web,dev]" \
    && mkdir -p /app/data /workspaces \
    && chown -R coding-agent:coding-agent /app /workspaces

USER coding-agent

EXPOSE 8000

CMD ["coding-agent-web"]
