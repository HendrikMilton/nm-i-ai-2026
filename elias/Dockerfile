FROM python:3.12-slim

RUN apt-get update && apt-get install -y curl git && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

COPY requirements.txt .

RUN pip install -r requirements.txt

WORKDIR /workspace

ENTRYPOINT ["claude"]
