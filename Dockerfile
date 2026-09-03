FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends git && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /repo

COPY daily.sh /daily.sh
RUN sed -i 's/\r$//' /daily.sh && chmod +x /daily.sh

CMD ["/daily.sh"]
