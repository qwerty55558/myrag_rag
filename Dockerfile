FROM python:3.13-slim

# 시스템 의존성: git (proto 패키지 설치) + Tesseract OCR + 한국어 언어팩
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    tesseract-ocr \
    tesseract-ocr-kor \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# uv 설치
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# GitHub private repo 접근용 (빌드 시에만 사용, 최종 이미지에 남지 않음)
ARG GITHUB_TOKEN
RUN git config --global url."https://x-access-token:${GITHUB_TOKEN}@github.com/".insteadOf "https://github.com/"

# 의존성 설치
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 소스 복사
COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 50051

CMD ["uv", "run", "python", "-m", "app.grpc_server"]
