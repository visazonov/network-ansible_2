FROM python:3.11-slim

WORKDIR /ansible

# Keep collections outside /ansible: Compose bind-mounts the repo over WORKDIR.
ENV ANSIBLE_COLLECTIONS_PATH=/usr/share/ansible/collections

RUN apt-get update \
    && apt-get install -y --no-install-recommends git gcc libssh-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt \
    && ansible-galaxy collection install \
        cisco.ios \
        arista.eos \
        ansible.netcommon \
        --collections-path "${ANSIBLE_COLLECTIONS_PATH}"
