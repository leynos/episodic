#!/usr/bin/env bash
set -euo pipefail

EXECUTION_MODE=${EXECUTION_MODE:-apply}
OUTPUT_DIR=${OUTPUT_DIR:-out}
ENVIRONMENT=${ENVIRONMENT:?ENVIRONMENT is required}
TF_WORKDIR=${TF_WORKDIR:-infra/clusters/${ENVIRONMENT}}

mkdir -p "${OUTPUT_DIR}"

write_result() {
  local status=$1
  cat <<JSON > "${OUTPUT_DIR}/provision-result.json"
{
  "status": "${status}",
  "execution_mode": "${EXECUTION_MODE}",
  "environment": "${ENVIRONMENT}",
  "workdir": "${TF_WORKDIR}"
}
JSON
}

if [[ "${EXECUTION_MODE}" == "validate" ]]; then
  if [[ ! -d "${TF_WORKDIR}" ]]; then
    echo "OpenTofu workdir not found: ${TF_WORKDIR}" >&2
    exit 1
  fi
  write_result "ok"
  exit 0
fi

if ! command -v tofu >/dev/null 2>&1; then
  echo "OpenTofu must be installed for provisioning." >&2
  exit 1
fi

if [[ -z "${DIGITALOCEAN_TOKEN:-}" ]]; then
  echo "DIGITALOCEAN_TOKEN must be set for provisioning." >&2
  exit 1
fi

export TF_IN_AUTOMATION=1

if [[ ! -d "${TF_WORKDIR}" ]]; then
  echo "OpenTofu workdir not found: ${TF_WORKDIR}" >&2
  exit 1
fi

tofu -chdir="${TF_WORKDIR}" init -input=false

tofu -chdir="${TF_WORKDIR}" plan -input=false -out=tfplan.binary

tofu -chdir="${TF_WORKDIR}" apply -input=false -auto-approve tfplan.binary

write_result "ok"
