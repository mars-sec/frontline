FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY frontline/ frontline/
COPY config/ config/

RUN pip install --no-cache-dir ".[claude,embeddings]" && \
    apt-get update && apt-get install -y --no-install-recommends git && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY daily.sh .
RUN chmod +x daily.sh

VOLUME /app/data
VOLUME /app/editions

CMD ["./daily.sh"]
