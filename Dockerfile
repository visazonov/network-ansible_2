FROM python:3.11-slim

WORKDIR /ansible

# Keep collections outside /ansible: Compose bind-mounts the repo over WORKDIR.
ENV ANSIBLE_COLLECTIONS_PATH=/usr/share/ansible/collections

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt \
    && ansible-galaxy collection install \
        cisco.ios \
        arista.eos \
        ansible.netcommon \
        --collections-path "${ANSIBLE_COLLECTIONS_PATH}"
