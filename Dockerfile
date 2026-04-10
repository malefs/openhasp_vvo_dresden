FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./

# create venv + install dependencies
RUN uv venv
RUN uv sync --frozen --no-dev

COPY . .

# uv automatically activates the correct environment
CMD ["uv", "run", "main.py"]


