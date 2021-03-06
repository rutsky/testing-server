FROM ubuntu:xenial

MAINTAINER Vladimir Rutsky <vladimir@rutsky.org>

RUN apt-get update && apt-get install -y \
    git \
    libpython3.5 \
    libpq-dev \
    python3-venv \
    sudo \
    subversion \
    && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m user -s /bin/bash

RUN su -l user -c "python3 -m venv --copies /home/user/env;"
RUN su -l user -c "source /home/user/env/bin/activate; pip install -U pip setuptools wheel"

ENV TESTING_SERVER_VER v0.1.20

# Workaround for <https://github.com/saltstack/pytest-logging/pull/7>
RUN su -l user -c "/home/user/env/bin/pip install git+https://github.com/rutsky/pytest-logging@fix-setup-py-encoding"
RUN su -l user -c "/home/user/env/bin/pip install -r https://raw.githubusercontent.com/rutsky/testing-server/${TESTING_SERVER_VER}/requirements.txt"
RUN su -l user -c "/home/user/env/bin/pip install git+https://github.com/rutsky/testing-server.git@${TESTING_SERVER_VER}"

EXPOSE 8080
USER user
ENTRYPOINT ["/home/user/env/bin/testing-server", "-H", "0.0.0.0", "-P", "8080"]
