# Linux seller-processing sandbox contract v1

`scripts/linux_bwrap_runner.py` is the production implementation of this
contract. `process_assets.py` refuses to process a seller file unless that
runner is explicitly configured. `--allow-unsafe-direct` exists only for the
local official-Blender fixture and must never appear in a production service.

## Deployment boundary

The v1 production host is Linux with cgroup v2, Bubblewrap, libseccomp, and a
pinned official Blender 5.2 Linux bundle. The worker runs as a dedicated
unprivileged `sulu-market-worker` account under
`scripts/deploy/sulu-market-asset-worker.service`.

The systemd unit is part of the sandbox, not optional tuning. The runner reads
its own cgroup and fails closed unless all of these kernel limits are active:

- `memory.max` at or below 48 GiB, with swap disabled by the unit;
- `pids.max` at or below 256;
- `cpu.max` at or below eight cores;
- systemd `RuntimeMaxSec`, the processor wrapper timeout, and the runner
  watchdog bound lifetime at separate layers;
- `LimitFSIZE=4 GiB` bounds every individual regular output file.

The larger memory ceiling accounts for Blender plus a kernel-enforced tmpfs
that can hold the canonical maximum of 16 GiB of artifacts and previews. Deployments may
lower these limits after measuring their accepted content, but may not raise
them without a new sandbox policy version and backend pin.

## Filesystem and process isolation

Bubblewrap creates new user, mount, PID, IPC, UTS, cgroup, and network
namespaces with `--unshare-all`. The process runs as UID/GID 65534 inside the
user namespace, with a new session, parent-death kill behavior, a fresh
`/proc`, a minimal `/dev`, an empty environment, and no host home or D-Bus
socket. Network isolation is not a convention: the new network namespace has
no host interface. Blender is additionally launched with `--offline-mode`.

The sandbox sees only:

- `/usr`, the pinned Blender bundle, and the processor source, all read-only;
- the exact staged `.blend`, trusted legal metadata, and immutable-ID mapping,
  each as an individual read-only bind;
- bounded tmpfs mounts for `/tmp` and `/job`.

No host directory is writable in the sandbox. Results are created in the
size-limited `/job` tmpfs and streamed as tar bytes over stdout after Blender
exits successfully. The trusted parent accepts only `manifest.json`,
`artifacts/<sha256>.blend`, and `previews/<sha256>.png`; previews have an
additional 16 MiB per-file cap. Links, devices, duplicates, traversal, unknown
paths, per-file overflow, aggregate overflow, and count overflow are rejected
before the extracted server-side result directory is atomically published. The
trusted wrapper and worker then require exact manifest coverage and fully
validate each PNG. Processor logs use stderr, so they cannot corrupt the result
channel.

The libseccomp policy is applied by Bubblewrap after namespace construction.
It denies mount/namespace mutation, ptrace, BPF/perf, kernel module and kexec
operations, keyring access, swap/reboot, `open_by_handle_at`, and io_uring
setup. Bubblewrap also disables creation of further user namespaces. The
policy intentionally remains an explicit denylist around a pinned Blender
build; changing Blender or its syscall needs requires a new audited sandbox
policy version.

Bubblewrap is a policy construction tool, not a complete policy on its own.
This repository owns and tests the exact arguments, following the upstream
security guidance on mount visibility, namespaces, new sessions, and seccomp:
<https://github.com/containers/bubblewrap#sandboxing>.

## Runner invocation

`process_assets.py` invokes:

```text
linux_bwrap_runner.py \
  --contract-version 1 \
  --input-ro SOURCE.blend \
  --output-rw NEW_RESULT_DIRECTORY \
  --trusted-metadata-ro TRUSTED.json \
  [--mappings-ro MAPPINGS.json] \
  --blender-ro PINNED_BLENDER \
  --processor-ro process_assets_blender.py \
  --timeout-seconds N \
  -- HARDENED_BLENDER_COMMAND...
```

The runner parses the inner command and rebuilds it with fixed sandbox paths.
It rejects extra Blender flags, unknown processor flags, path disagreement,
and limits above 4 GiB source, 4 GiB per artifact, 16 GiB aggregate, or 500
assets. Passing an arbitrary command through this interface is not supported.

## Production setup

1. Install the pinned Bubblewrap/libseccomp packages and an audited official
   Blender 5.2 Linux bundle. Record the exact Blender version and build hash.
2. Install this repository's `scripts/` tree read-only under
   `/opt/sulu-market-bridge/scripts` and make `linux_bwrap_runner.py`
   executable.
3. Create the dedicated service user and a mode-0700
   `/var/lib/sulu-market-worker` directory owned by it.
4. Install `scripts/deploy/sulu-market-asset-worker.service`, create the
   root-owned mode-0600 environment file from the example, then enable the
   service.
5. Set the backend job pin to sandbox policy `linux-bwrap-v1`, the exact
   processor version, Blender version, and Blender build hash. A mismatch
   leaves jobs unclaimed.
6. Run the mock worker protocol test and the official Blender processor E2E in
   CI. Run the Linux sandbox smoke test on the production image before rollout;
   macOS cannot validate Linux namespaces, cgroups, or seccomp.

The runner deliberately refuses to degrade when cgroup v2, Bubblewrap,
libseccomp, user namespaces, or required paths are unavailable.
