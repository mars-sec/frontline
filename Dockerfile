FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /install
COPY pyproject.toml README.md LICENSE ./
COPY frontline/ frontline/
RUN pip install --no-cache-dir ".[claude,embeddings]"

COPY daily.sh /daily.sh
RUN chmod +x /daily.sh

WORKDIR /repo

CMD ["/daily.sh"]
