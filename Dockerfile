FROM ubuntu:xenial

MAINTAINER Vladimir Rutsky <vladimir@rutsky.org>

RUN apt-get update && apt-get install -y \
    python3-venv \
    sudo \
    libpython3.5 \
    && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y \
    git \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y \
    subversion \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m user -s /bin/bash

RUN su -l user -c "python3 -m venv --copies /home/user/env;"
RUN su -l user -c "source /home/user/env/bin/activate; pip install -U pip setuptools wheel"
RUN su -l user -c "/home/user/env/bin/pip install git+https://github.com/rutsky/testing-server.git"

EXPOSE 8080
USER user
ENTRYPOINT ["/home/user/env/bin/testing-server", "-H", "0.0.0.0", "-P", "8080"]
