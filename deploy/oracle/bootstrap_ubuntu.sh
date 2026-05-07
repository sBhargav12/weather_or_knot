#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/ubuntu/prediction-market-analysis}"
SWAP_FILE="${SWAP_FILE:-/swapfile}"
SWAP_SIZE="${SWAP_SIZE:-4G}"

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  build-essential \
  ca-certificates \
  curl \
  git \
  libeccodes-dev \
  pkg-config

if ! swapon --show=NAME | grep -qx "${SWAP_FILE}"; then
  if [ ! -f "${SWAP_FILE}" ]; then
    sudo fallocate -l "${SWAP_SIZE}" "${SWAP_FILE}"
    sudo chmod 600 "${SWAP_FILE}"
    sudo mkswap "${SWAP_FILE}"
  fi
  sudo swapon "${SWAP_FILE}"
fi

if ! grep -qE "^[^#].*${SWAP_FILE}" /etc/fstab; then
  echo "${SWAP_FILE} none swap sw 0 0" | sudo tee -a /etc/fstab >/dev/null
fi

if [ ! -x /home/ubuntu/.local/bin/uv ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

cd "${REPO_DIR}"
/home/ubuntu/.local/bin/uv sync --frozen

sudo install -o root -g root -m 0644 deploy/oracle/kalshi-paper.service /etc/systemd/system/kalshi-paper.service
sudo install -o root -g root -m 0644 deploy/oracle/kalshi-collector.service /etc/systemd/system/kalshi-collector.service
sudo systemctl daemon-reload
