# Alpha test notes: no-QA generation on the local podman/kind preview

Date: 2026-08-22. Branch:
`4-3-2-no-qa-generation-runs-and-tei-p5-retrieval-alpha-feedback`.

Goal: generate a TEI P5 episode script from a source document (an Aldus
PageMaker history) and a show specification (*Worlds Apart*) using the roadmap
`4.3` source-to-script vertical slice, on the local podman/kind preview
cluster, and record what it took.

## Environment

- Fedora-family Linux under WSL2, rootless Podman 5.8.0.
- `docker` on the PATH is the Podman shim (`podman-docker`), not real Docker.
- `helm`, `uv`, and `jq` were already present.

## Tools installed during the test

| Tool        | Version | How installed                                            |
| ----------- | ------- | -------------------------------------------------------- |
| `kind`      | v0.32.0 | Binary download from GitHub releases into `~/.local/bin` |
| `kubectl`   | v1.36.4 | Binary download from `dl.k8s.io` into `~/.local/bin`     |
| `e2fsprogs` | 1.47.3  | `sudo dnf install e2fsprogs` (superblock checks)         |

Neither `kind` nor `kubectl` was present, although the users' guide preview
workflow requires both. `k3d` was also absent, so the k3d default provider was
never an option on this host; the documented rootless-Podman guidance (use
`LOCAL_K8S_ENGINE=podman LOCAL_K8S_PROVIDER=kind`) is the path taken.

## Log

(Chronological; updated as the test progresses.)

- Confirmed input files exist: `~/docs/the-crown-and-the-pasetboard.md`
  (source document — note the filename typo "pasetboard" is in the file system,
  not this document), `~/docs/worlds-apart.md` (show spec), and
  `~/gpt-image-2-key.txt` (OpenAI key).
- The users' guide (`docs/users-guide.md`) documents the intended workflow
  clearly: `POST /v1/uploads` → `POST /v1/ingestion-jobs` → attach source →
  poll job → `POST .../generation-runs` with `quality_mode=draft_without_qa` →
  poll run → `GET /v1/episodes/{id}/tei` with `Accept: application/tei+xml`.
- Installed `kind` and `kubectl` (see table above). The first `kind`
  download used the `latest` channel, which served an alpha build
  (0.33.0-alpha); replaced it with the stable v0.32.0 release.
- **First `make local-k8s-up LOCAL_K8S_ENGINE=podman LOCAL_K8S_PROVIDER=kind`
  failure — netavark firewall rules.** `kind create cluster` failed at
  "Preparing nodes" with
  `netavark: nftables error: "nft" did not return successfully`. Two
  compounding causes on this WSL2 host:
  - The WSL2 kernel (6.6.87.2-microsoft) builds `nf_tables` in, but leaves
    `CONFIG_NFT_FIB_IPV6` unset, so netavark's default nftables driver
    cannot install its ruleset ("Could not process rule: No such file or
    directory").
  - Switching netavark to the iptables driver
    (`~/.config/containers/containers.conf` →
    `[network] firewall_driver = "iptables"`) then failed because no
    `iptables` binary was installed.

  Fix: `sudo dnf install -y iptables-nft` plus the `containers.conf` snippet
  above, then `podman network rm kind` so the network is recreated with the
  working driver. A plain `podman run --net podman alpine true` is a useful
  smoke test — this failure is a host-podman problem, not an Episodic one, but
  the preview docs assume container networking already works.
- A second `local-k8s-up` failure mode worth recording: the wrapper runs
  every command with `capture_output=True` and lets `CalledProcessError`
  escape, so the operator sees a Python traceback with **no stderr from the
  failing command**. Diagnosing the netavark failure required re-running the
  `kind create cluster` command by hand. `scripts/local_k8s/commands.py` should
  surface captured stderr on failure (fixed in this branch: the runner now
  echoes captured output before re-raising).
- **The documented preview cannot boot the API service at all.** The local
  chart values only supplied `EPISODIC_ENV` and `DATABASE_URL`, but
  `episodic/api/runtime_config.py` refuses to start without
  `SOURCE_INTAKE_OBJECT_STORE_ROOT`, `API_AUTHORIZATION_BEARER_TOKEN`, and
  `API_AUTHORIZATION_PRINCIPAL_ID`, and it validates the pricing-snapshot
  directory at boot. The users' guide describes `make local-k8s-up` as
  producing a working service; in reality the pod could never have passed
  boot-time configuration validation. Fixes made on this branch:
  - `Dockerfile` now copies `config/pricing-snapshots` into the runtime
    image. The default path in code resolves relative to the installed
    package (site-packages), so the ConfigMap sets
    `PRICING_SNAPSHOT_DIRECTORY=/app/config/pricing-snapshots` explicitly.
  - `charts/episodic/values.local.yaml` adds the boot-required settings,
    plus optional `OPENAI_BASE_URL`/`OPENAI_API_KEY` secret references so
    generation can reach a real provider.
  - The chart originally had **no volume support**, and the container runs
    with `readOnlyRootFilesystem: true`, so the source-intake object store
    had nowhere to write. The chart now accepts pass-through `volumes` and
    `volumeMounts` values, and the local values mount an `emptyDir` at
    `/tmp`; the container keeps its read-only root filesystem.
  - `scripts/local_k8s` now writes `api-bearer-token` (default
    `local-dev-token`) into the preview secret, and, when `OPENAI_API_KEY`
    is present in the operator's environment, the paired
    `openai-base-url`/`openai-api-key` literals.
  - Helm chart contract tests pinned the old (non-booting) ConfigMap and
    env exactly; they are updated to the new contract.
- First deploy raced these fixes and sat in `CreateContainerConfigError`
  (the pre-fix secret lacked `api-bearer-token`); a second
  `OPENAI_API_KEY=... make local-k8s-up` run rebuilt and redeployed.
- **kube-proxy crashloop → cluster DNS dead.** With the app booting, readiness
  stayed red: `/health/ready` returned 503 because the pod could not resolve
  `postgres`. CoreDNS was not ready because kube-proxy was in CrashLoopBackOff
  with `failed complete: too many open files` — the well-known kind-on-Linux
  inotify exhaustion. Fix:
  `sudo sysctl -w fs.inotify.max_user_watches=524288
  fs.inotify.max_user_instances=512`
  (the host already had 524288 watches but only 128 instances) and delete the
  kube-proxy pod. The repo's local preview documentation does not mention this
  prerequisite.
- **Migrations are a manual, undocumented-for-k8s step.** The users' guide
  says "apply the latest Alembic migrations" but the preview provides no hook.
  Applied from the host through a port-forward:
  `kubectl -n episodic port-forward svc/postgres 15432:5432` then
  `DATABASE_URL=postgresql+asyncpg://episodic:episodic@127.0.0.1:15432/episodic
  uv run alembic upgrade head`.
  This worked first time.
- **Driving the API worked as documented.** With a port-forward on
  `svc/episodic` (8088:80), the documented 4.3 slice behaved exactly as the
  users' guide describes: series profile → host-profile reference documents →
  revisions → series bindings → two uploads (source document and show
  specification) → ingestion job → source attachments (the job flips to
  `ready_for_generation` on first attachment) → `POST .../generation-runs` with
  `quality_mode=draft_without_qa` → poll → episode TEI. Payload shapes had to
  be read from the resource code (`episodic/api/resources/`); the users' guide
  names the endpoints but not the request bodies.
- **First generation run failed: `LLM response is not valid JSON.`** The
  OpenAI adapter never requests a constrained response format, and the default
  draft system prompt merely asks for JSON, so `gpt-4o-mini` wrapped its JSON
  in markdown fences and the fail-fast parser (correctly) rejected it. Fixed on
  this branch by adding `json_response: bool` to `LLMRequest`, emitting
  `response_format={"type": "json_object"}` (chat completions) / `text.format`
  (Responses API), and setting it from the draft script generator. Unit tests
  added in `tests/test_llm_openai_request_payload.py`.
- **Model switch to `gpt-5.6-sol` (operator request) exposed three adapter
  gaps.** Probing the model directly showed: (1) reasoning models reject
  `max_tokens` and require `max_completion_tokens`; (2) the flex service tier
  was capacity-constrained ("Flex does not have sufficient resources… change
  service_tier=default"), so the preview runs on the default tier; (3) there
  was no way to set `reasoning_effort`. Added `OpenAIPayloadOptions` (reasoning
  effort, service tier, token-limit parameter name) to the adapter, wired
  through new runtime settings `OPENAI_REASONING_EFFORT`,
  `OPENAI_SERVICE_TIER`, and `OPENAI_TOKEN_LIMIT_PARAM`. The local preview pins
  `DRAFT_MODEL=gpt-5.6-sol`, effort `low`, default tier.
- **Cost pinning requires a pricing snapshot for the current month.** The
  pricing catalogue is exact-match on provider/model/operation/billing period,
  and a missing snapshot fails the whole generation run. Added
  `config/pricing-snapshots/openai-2026-08.yaml` for `gpt-5.6-sol` (USD 2.00/M
  input, 10.00/M output, 0.20/M cached input).
- **Second failure mode: `Transient provider failure after exhausting retries.`
  ** The adapter's HTTP timeout was hard-coded at 30 s; a reasoning model
  drafting a full episode script comfortably exceeds that, so every attempt was
  cancelled client-side and retried until the run failed. Host-side curl proved
  the provider and pod egress were both healthy. Fixed by adding
  `OPENAI_TIMEOUT_SECONDS` (default 30, local preview sets 600).
- **The WSL2 VM itself crashed twice during image rebuilds**, taking the
  kind container with it. Recovery each time:
  `systemd-run --scope --user -p Delegate=yes podman start
  episodic-preview-control-plane`,
  wait for the API server, then let the pods restart. The inotify sysctls were
  lost on the first restart, so they are now persisted in
  `/etc/sysctl.d/99-kind-inotify.conf` (confirmed to survive the second
  restart). The crashes look like a WSL platform issue rather than anything
  kind or podman did.
- **The object store is pod-ephemeral, but upload rows are not.** After a
  pod restart, uploads recorded in Postgres point at blobs under
  `/tmp/episodic-object-store` that no longer exist, and a generation run then
  fails with `[Errno 2] No such file or directory`. The database (a StatefulSet
  with a PVC) and the object store (container tmpfs) have different lifetimes;
  the object store needs a volume with a lifetime matched to the upload
  rows. This branch adds the `emptyDir` mount (which still dies with the
  pod) and documents in the users' guide that uploads must be redone after
  any application pod restart; durable blob storage remains follow-up work.
- **`make local-k8s-up` refuses to run while its own port-forward is
  alive.** The preview tooling validates that port 8088 is free, so an operator
  following the docs (which say to keep a port-forward running) cannot re-run
  the up command without first killing their own kubectl.
- **The second WSL crash corrupted rootless podman's overlay storage.**
  `podman build` failed with `readlink …/overlay/l: invalid argument`; the
  layer link directory `~/.local/share/containers/storage/overlay/l` had been
  destroyed and several layers had truncated (empty) `link` files. Repaired
  without a `podman system reset` (which would have destroyed the running kind
  cluster's storage) by removing stale buildah working containers
  (`buildah rm --all`), recreating `overlay/l`, and regenerating one symlink
  per layer from each layer's `link` file
  (`ln -sfn ../<layer>/diff l/<link-id>`). The subsequent build succeeded from
  cache.
- **Third failure mode: pricing pins violate a foreign key on a fresh
  database.** With the timeout fixed, the draft generated successfully
  (`draft.generated`, `finish_reason=stop`), but the run then failed:
  `run_pricing_pins.pricing_snapshot_id` references `pricing_snapshots.id`, and
  nothing ever syncs the file-based pricing catalogue
  (`config/pricing-snapshots/*.yaml`) into that table. The first run to reach
  cost pinning on any fresh deployment can only fail. Fixed on this branch by
  adding `ensure_snapshot` to `CostLedgerPort`: the recorder now persists the
  resolved snapshot (idempotent `ON CONFLICT DO NOTHING` on the immutable
  snapshot id) before pinning it or recording a provider call against it.
- **Fixed `make skylos-allow` and its lint noise.** Two independent
  defects: Skylos parses sources with its own runtime's `ast`, so without
  `uv tool run --python 3.14` an older default interpreter misreads 3.14
  syntax and reports phantom dead code (fix cherry-picked from the
  `code-duplication-gate` branch); and the `whitelist` subcommand only
  dispatches when it is Skylos's first argument, so the shared macro's
  `--config-file` prefix made `--reason` an "unrecognized argument". The
  target now uses a bare `SKYLOS_CLI` macro for the subcommand and accepts
  `NAME`/`REASON` only from the make command line, so an ambient `NAME`
  environment variable can no longer leak into the whitelist (the full
  test suite had previously written the host's `NAME=ibara` and a
  shell-injection probe into the real `pyproject.toml`).
- **Storage post-mortem after the third crash (whole-PC restart).** The
  ext4 superblock on the distro disk reports `clean` with no recorded
  error history, and podman's overlay layer links survived intact this
  time. The overlay driver configuration itself is sound: native kernel
  overlayfs (not fuse-overlayfs) on ext4, `d_type` supported. The
  corruption pattern (EIO on every process spawn, journald files
  corrupted, overlay link directory destroyed once) with no ext4 error
  records points at lost writes in the WSL2 VHDX/virtio-blk layer when
  the VM dies under container-build I/O, not at podman or kind. Worth
  checking on the Windows side: Event Viewer disk/vhdmp events around the
  crash times and free space on the drive holding the VHDX. Moving
  podman's `graphroot` off the distro VHDX onto the separate `/data`
  disk would also take the build I/O out of the blast radius.
- **Success.** With all fixes deployed (JSON response mode,
  `max_completion_tokens`, 600 s timeout, snapshot persistence,
  zero-metric suppression, and the `emptyDir` mount under a read-only
  root filesystem), the full workflow completed end to end: series
  profile → host reference documents and bindings → source document and
  show specification uploads → ingestion job → source attachment →
  `draft_without_qa` generation run → `run.succeeded` → TEI P5 download
  via `Accept: application/tei+xml`. The `gpt-5.6-sol` draft consumed
  13,803 input and 2,476 output tokens (≈ USD 0.05 at the pinned
  2026-08 rates) and produced a 10 kB, 39-turn TEI document whose
  dialogue follows the show specification's host personas and the
  source document's narrative arc.
