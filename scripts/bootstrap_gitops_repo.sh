#!/usr/bin/env bash
set -euo pipefail

EXECUTION_MODE=${EXECUTION_MODE:-apply}
OUTPUT_DIR=${OUTPUT_DIR:-out}
GITOPS_ORG=${GITOPS_ORG:?GITOPS_ORG is required}
GITOPS_REPO=${GITOPS_REPO:?GITOPS_REPO is required}
GITOPS_BRANCH=${GITOPS_BRANCH:-main}
GITOPS_TEMPLATE_DIR=${GITOPS_TEMPLATE_DIR:-infra/gitops-template}
FLUX_DEPLOY_KEY_TITLE=${FLUX_DEPLOY_KEY_TITLE:-flux-deploy-key}

mkdir -p "${OUTPUT_DIR}"

GITOPS_TEMPLATE_DIR=$(realpath "${GITOPS_TEMPLATE_DIR}")

write_result() {
  local status=$1
  cat <<JSON > "${OUTPUT_DIR}/bootstrap-result.json"
{
  "status": "${status}",
  "execution_mode": "${EXECUTION_MODE}",
  "gitops_org": "${GITOPS_ORG}",
  "gitops_repo": "${GITOPS_REPO}",
  "gitops_branch": "${GITOPS_BRANCH}",
  "template_dir": "${GITOPS_TEMPLATE_DIR}"
}
JSON
}

if [[ "${EXECUTION_MODE}" == "validate" ]]; then
  if [[ ! -d "${GITOPS_TEMPLATE_DIR}" ]]; then
    echo "Template directory not found: ${GITOPS_TEMPLATE_DIR}" >&2
    exit 1
  fi
  write_result "ok"
  exit 0
fi

if [[ -z "${GITHUB_TOKEN:-}" && -z "${GH_TOKEN:-}" ]]; then
  echo "GITHUB_TOKEN or GH_TOKEN must be set for GitHub access." >&2
  exit 1
fi

export GH_TOKEN=${GH_TOKEN:-${GITHUB_TOKEN}}

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI is required to bootstrap the GitOps repository." >&2
  exit 1
fi

if ! command -v vault >/dev/null 2>&1; then
  echo "vault CLI is required to store deploy keys." >&2
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git is required to seed the GitOps repository." >&2
  exit 1
fi

if ! command -v ssh-keygen >/dev/null 2>&1; then
  echo "ssh-keygen is required to create deploy keys." >&2
  exit 1
fi

VAULT_ADDR=${VAULT_ADDR:?VAULT_ADDR is required}
VAULT_TOKEN=${VAULT_TOKEN:?VAULT_TOKEN is required}
VAULT_KV_PATH=${VAULT_KV_PATH:?VAULT_KV_PATH is required}

repo_slug="${GITOPS_ORG}/${GITOPS_REPO}"

if ! gh repo view "${repo_slug}" >/dev/null 2>&1; then
  visibility=${GITOPS_VISIBILITY:-private}
  if [[ "${visibility}" == "public" ]]; then
    gh repo create "${repo_slug}" --public --confirm
  else
    gh repo create "${repo_slug}" --private --confirm
  fi
fi

tmpdir=$(mktemp -d)
trap 'rm -rf "${tmpdir}"' EXIT

repo_dir="${tmpdir}/repo"

gh repo clone "${repo_slug}" "${repo_dir}"

cd "${repo_dir}"

git checkout -B "${GITOPS_BRANCH}"

git config user.name "episodic-automation"
git config user.email "infra-bot@users.noreply.github.com"

rsync -a --delete --exclude '.git' "${GITOPS_TEMPLATE_DIR}/" "${repo_dir}/"

git add -A
if ! git diff --cached --quiet; then
  git commit -m "Bootstrap GitOps repository"
  git push origin "${GITOPS_BRANCH}"
fi

existing_key_id=$(gh api "/repos/${repo_slug}/keys" --jq \
  ".[] | select(.title == \"${FLUX_DEPLOY_KEY_TITLE}\") | .id" | head -n 1)

if [[ -z "${existing_key_id}" ]]; then
  key_dir="${tmpdir}/keys"
  mkdir -p "${key_dir}"
  ssh-keygen -t ed25519 -C "${FLUX_DEPLOY_KEY_TITLE}" -f "${key_dir}/flux" -N ""

  gh api --method POST "/repos/${repo_slug}/keys" \
    -f title="${FLUX_DEPLOY_KEY_TITLE}" \
    -f key="$(cat "${key_dir}/flux.pub")" \
    -F read_only=true

  vault kv put "${VAULT_KV_PATH}" \
    flux_deploy_key="$(cat "${key_dir}/flux")" \
    flux_deploy_public_key="$(cat "${key_dir}/flux.pub")"
fi

write_result "ok"
