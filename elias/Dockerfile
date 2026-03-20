FROM python:3.12-slim

RUN apt-get update && apt-get install -y curl git jq && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

# Python deps
COPY requirements.txt .
RUN pip install -r requirements.txt

# Frontend deps — install into image so container startup is fast
COPY frontend/package.json frontend/package-lock.json /opt/frontend/
RUN cd /opt/frontend && npm install

RUN useradd -m -s /bin/bash claude

WORKDIR /workspace
RUN chown claude:claude /workspace

USER claude

COPY entrypoint.sh /opt/entrypoint.sh
ENTRYPOINT ["/opt/entrypoint.sh"]
