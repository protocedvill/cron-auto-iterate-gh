# cron-auto-iterate-gh

A cron-triggered script that uses headless Claude Code to make one small,
autonomous improvement to one of the user's projects per run, validates it,
and pushes it directly to the project's main branch. Progress across runs is
tracked via a `TODO.md` backlog file living in each target repo. The whole
thing runs as an unprivileged, isolated system account with no access to the
human user's files.

## Design decisions (locked in)

| Decision | Choice | Rationale |
|---|---|---|
| Agent driver | Headless `claude` CLI (`claude -p`) | Reuses the tool already installed; no SDK integration needed. |
| Task source | Per-repo `TODO.md` backlog | Gives continuity across runs; falls back to self-generated ideas when empty. |
| Push strategy | Direct push to the repo's default branch | Matches original intent; no PR review step. |
| Scheduling | systemd timer + service (see Isolation section) | Same trigger model as cron, but gets sandboxing directives cron lacks. |
| Target repos | Configurable list (not hardcoded) | One tool instance can tend multiple projects. |
| Validation gate | Run each repo's configured test/build command before pushing | Prevents pushing broken changes; roll back on failure. |
| Run record | The git commit itself (message + diff) | No separate notification channel; history lives in git log. |
| Guardrails | Forbidden-path denylist (`.git/`, `.env*`, CI config, secrets) | Blocks the agent from touching sensitive files, no size cap for now. |
| Script language | Python 3 | Easier JSON/YAML config handling, path/diff checks than bash. |
| Repo selection per run | Round-robin over the configured list, one repo per run | Spreads iterations evenly; state persisted between runs. |
| Cron frequency | Daily | Low cost, enough time to notice a bad change before the next one lands. |
| Empty backlog behavior | Generate 3-5 new ideas into `TODO.md`, commit just that file, stop | Keeps "brainstorm" and "implement" as separate, independently-reviewable commits. |
| Dirty/unsynced repo at start | Abort this run for that repo, try again next scheduled run | Never touch a repo with the user's own in-progress work. |
| Agent permissions | `claude --dangerously-skip-permissions`, invoked with `cwd` set to the target repo | Scopes blast radius to that one repo's directory by construction. |
| Cost/runtime cap | `--max-turns` on the claude CLI + wall-clock `timeout` wrapper (e.g. 15 min) | Bounds token spend and prevents a hung run from blocking the next cron tick. |
| **Execution identity** | **Dedicated unprivileged system user (`cron-iterate`), no shell login** | Isolates the automation from the human user's account entirely; a misbehaving agent run can't read/write anything outside what this user owns. |
| **Repo access model** | **Dedicated clones under `/var/lib/cron-iterate/repos/`, owned by that user** | The automation never needs to enter the human's `$HOME`. Human's own working copy stays untouched; a `git pull` picks up pushed changes. |
| **Code deployment model** | **Tool code deployed read-only to `/opt/cron-auto-iterate-gh`, owned by root** | The dev copy of this tool (in this repo, under the human's home dir) is what gets edited/committed; a separate deploy step copies it to a root-owned, cron-iterate-read-only location so the agent can't modify its own automation code even if it tried. |
| **Sandbox layer** | **systemd service + timer with hardening directives** (`ProtectHome`, `ProtectSystem=strict`, `NoNewPrivileges`, etc.) | Enforces the isolation at the kernel/namespace level, independent of Unix file permissions — defense in depth over just "a different UID". |
| **Git push credentials** | **Single SSH keypair generated for `cron-iterate`, added as a GitHub deploy key (write access) on each target repo individually** | One key to manage, but still repo-scoped (GitHub deploy keys are per-repo) rather than tied to a personal account token — compromise is contained to the configured repos. |
| **Claude Code credentials** | **Copy of the human's existing Claude Code credentials, placed in `cron-iterate`'s own home dir** | Shares the existing login/subscription as requested, without granting `cron-iterate` read access into the human's `$HOME` to fetch it live — it's a one-time copy the automation user owns outright. |

## Isolation & sandboxing

### 1. Dedicated system user

```bash
sudo useradd --system --home-dir /var/lib/cron-iterate --create-home \
  --shell /usr/sbin/nologin cron-iterate
```

- `--system`: no password login, treated as a service account.
- `--shell /usr/sbin/nologin`: cannot be used for an interactive shell session.
- Home dir `/var/lib/cron-iterate` (not under `/home`) so `ProtectHome=yes`
  (below) hides `/home` entirely without also hiding this user's own data.

Directory layout under `/var/lib/cron-iterate/` (all owned by `cron-iterate:cron-iterate`, mode 700):
```
/var/lib/cron-iterate/
├── repos/            # dedicated clones, one per configured target repo
├── logs/             # per-run claude transcripts
├── state.json         # round-robin pointer
├── config.yaml        # copy/symlink of the tool's config (see deployment below)
└── .ssh/
│   └── id_ed25519(.pub)   # single automation deploy-key pair
└── .claude/            # copied Claude Code credentials (see below)
```

### 2. Code deployment (dev repo vs. runtime)

This git repo (`/home/louis/OneDrive/notes/cron-auto-iterate-gh`) stays the
place where the tool's own code is written, reviewed, and committed. A
separate deploy step publishes it to a location `cron-iterate` can execute
but never write:

```bash
sudo mkdir -p /opt/cron-auto-iterate-gh
sudo rsync -a --delete iterate.py lib/ prompts/ /opt/cron-auto-iterate-gh/
sudo chown -R root:cron-iterate /opt/cron-auto-iterate-gh
sudo chmod -R 750 /opt/cron-auto-iterate-gh
```

`cron-iterate` gets read+execute (via group membership) but no write access
— even if the LLM agent tried to edit `iterate.py` itself (it never runs
with that as `cwd`, but belt-and-suspenders), it structurally can't.

### 3. Repo cloning & remote setup

For each repo in `config.yaml`:
```bash
sudo -u cron-iterate git clone git@github.com:<org>/<repo>.git \
  /var/lib/cron-iterate/repos/<repo>
```
These are independent clones from the human's own working copy of the same
GitHub repo — both point at the same remote, so pushes from one are visible
to the other via normal `git fetch`/`pull`.

### 4. Git credentials (single deploy key)

```bash
sudo -u cron-iterate ssh-keygen -t ed25519 -f /var/lib/cron-iterate/.ssh/id_ed25519 -N ""
```
Add the resulting public key as a **Deploy Key with write access** on each
target repo's GitHub settings page (Settings → Deploy keys → Add deploy
key). Reusing the same keypair across repos is fine — deploy keys are
scoped per-repo on GitHub's side regardless of how many repos reuse the same
public key, so a leak still only grants access to the repos where it was
explicitly added.

### 5. Claude Code credentials

Copy (don't symlink/share live) the credentials file into the new user's
own home, then lock down permissions:
```bash
sudo cp ~/.claude/.credentials.json /var/lib/cron-iterate/.claude/.credentials.json
sudo chown -R cron-iterate:cron-iterate /var/lib/cron-iterate/.claude
sudo chmod 600 /var/lib/cron-iterate/.claude/.credentials.json
```
Note: this uses the human's own subscription/login for usage — automation
spend is not separately tracked or capped. (If that turns out to matter,
switching to a dedicated Anthropic API key later is a config change, not an
architecture change.)

### 6. systemd service + timer (the sandbox layer)

`/etc/systemd/system/cron-iterate.service`:
```ini
[Unit]
Description=cron-auto-iterate-gh: one autonomous project iteration
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=cron-iterate
Group=cron-iterate
WorkingDirectory=/var/lib/cron-iterate
ExecStart=/usr/bin/python3 /opt/cron-auto-iterate-gh/iterate.py
TimeoutStartSec=1200

# Filesystem isolation
ProtectHome=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/cron-iterate
PrivateTmp=yes
PrivateDevices=yes

# Privilege / kernel surface restriction
NoNewPrivileges=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
RestrictSUIDSGID=yes
RestrictNamespaces=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
RestrictRealtime=yes
SystemCallFilter=@system-service
SystemCallArchitectures=native

# Network: only IP sockets, no raw/packet sockets
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX

# Resource caps
CPUQuota=200%
MemoryMax=4G
TasksMax=256
```

`/etc/systemd/system/cron-iterate.timer`:
```ini
[Unit]
Description=Daily trigger for cron-auto-iterate-gh

[Timer]
OnCalendar=daily
RandomizedDelaySec=1800
Persistent=true

[Install]
WantedBy=timers.target
```

Enable with `sudo systemctl enable --now cron-iterate.timer`. Service-level
logs (start/stop/exit code, stderr) land in the journal automatically
(`journalctl -u cron-iterate`); the per-run claude transcript still goes to
`/var/lib/cron-iterate/logs/` as planned.

**Key guarantee:** `ProtectHome=yes` makes `/home`, `/root`, and
`/run/user/*` invisible to this service at the kernel namespace level —
independent of Unix file permissions. Even a misconfigured ACL or a `chmod`
mistake on the human's files can't expose them to this process, because the
mount namespace never contains `/home` in the first place.

**Known limitation — network egress:** `IPAddressAllow=`/`IPAddressDeny=`
only match IP/CIDR literals, not hostnames, and both `api.anthropic.com`
and `github.com` sit behind rotating/CDN IPs — so systemd alone can't
cleanly restrict egress to "just these two services." Options if that's
wanted later are listed below (forward-proxy allowlist).

### Other sandboxing options considered (not chosen, for later reference)

Roughly in order of effort vs. additional benefit given systemd hardening
is already in place:

- **systemd-nspawn container** — a "container" without adding Docker as a
  dependency; already built into systemd on Fedora. Gives a full private
  root filesystem (only the specific repo bind-mounted in) rather than just
  namespace-hidden paths. Natural next step if `ProtectHome`/`ProtectSystem`
  ever feels insufficient.
- **Docker/Podman container** — strongest, most portable isolation, but adds
  an image to build/maintain and a layer of credential-passing (SSH key,
  Claude credentials) into the container. Worth it if this ever needs to run
  somewhere other than this one machine.
- **Egress allowlist via a local forward proxy** (tinyproxy/mitmproxy with a
  domain ACL for `api.anthropic.com` + `github.com`, `HTTPS_PROXY` set in the
  service's environment, plus an nftables rule rejecting outbound traffic
  from the `cron-iterate` UID that doesn't go through the proxy). Solves the
  "systemd can't match hostnames" limitation above; worth doing if you want
  to guarantee the process can *only* reach those two services and nothing
  else, even if the agent is somehow tricked into trying.
- **SELinux confined domain** — Fedora ships SELinux enabled by default;
  writing a custom policy type for `cron-iterate` adds mandatory access
  control on top of the discretionary Unix permissions already in place
  (protects against e.g. a `sudo` misconfiguration granting accidental
  access). Higher effort, most relevant if this machine runs other
  sensitive services too.
- **bubblewrap/firejail wrapper** around just the `claude` subprocess
  invocation (rather than the whole service) — a lighter-weight way to get
  container-like filesystem scoping for the one process that actually calls
  out to an LLM and edits files, without touching the surrounding systemd
  setup at all.
- **Separate Anthropic API key with a spend cap** — doesn't sandbox
  filesystem/network access, but bounds financial/usage blast radius, which
  matters once this runs unattended daily. Straightforward to add later
  without other architecture changes.

## Repository layout (this tool, dev copy)

```
cron-auto-iterate-gh/
├── plan.md
├── config.yaml          # list of target repos + per-repo overrides
├── iterate.py             # main entrypoint, deployed to /opt and run by systemd
├── lib/
│   ├── config.py          # load/validate config.yaml
│   ├── git_ops.py         # clean/up-to-date checks, commit, push, diff inspection
│   ├── guardrails.py       # forbidden-path checks against the diff
│   ├── backlog.py         # parse/update TODO.md (checklist format)
│   └── agent.py           # build and run the `claude -p ...` subprocess
├── prompts/
│   ├── implement_task.md  # template: "implement this TODO item"
│   └── brainstorm.md       # template: "propose 3-5 improvements"
└── deploy.sh              # rsyncs code to /opt/cron-auto-iterate-gh (see Isolation section)
```

Runtime state (`state.json`, `logs/`, repo clones, credentials) lives under
`/var/lib/cron-iterate/`, owned by that user — not in this dev repo.

## Configuration format (`config.yaml`)

```yaml
repos:
  - name: foo
    remote: git@github.com:louison/foo.git
    test_cmd: "npm test"
    todo_file: TODO.md          # default if omitted
    branch: main                 # default: repo's current HEAD branch
  - name: bar
    remote: git@github.com:louison/bar.git
    test_cmd: "make test"

defaults:
  max_turns: 40
  timeout_seconds: 900
  forbidden_paths:
    - ".git/**"
    - ".env*"
    - "**/*.pem"
    - "**/id_rsa*"
    - ".github/workflows/**"
    - "**/secrets/**"
```

Note: `path:` was replaced with `name:` + `remote:` — the actual on-disk
clone path is always derived as `/var/lib/cron-iterate/repos/<name>`, since
that's the only location `cron-iterate` is allowed to write to. This
removes an entire class of misconfiguration (accidentally pointing the
tool at a path under the human's `$HOME`).

`state.json` (auto-managed, not hand-edited):
```json
{ "last_index": 2 }
```

## TODO.md backlog format (in each target repo)

Standard GitHub checklist so it's human-readable and diffable:

```markdown
# Auto-iteration backlog

- [ ] Add input validation to `parse_config()` for missing required fields
- [ ] Extract duplicated retry logic in `client.py` and `worker.py` into a helper
- [x] Add a test for the empty-input case in `formatter.js`
```

- Unchecked (`- [ ]`) items are candidate tasks, top-to-bottom priority.
- The agent checks an item (`- [x]`) in the same commit that implements it.
- Completed items stay in the file as a log (not deleted) — cheap history of
  what's been done, avoids the agent re-proposing the same idea.

## `iterate.py` run sequence

1. **Load config** (`config.yaml`) and **state** (`state.json`), both under `/var/lib/cron-iterate/`.
2. **Pick repo**: `repos[state.last_index % len(repos)]`.
3. **Pre-flight checks** on `/var/lib/cron-iterate/repos/<name>` (abort + log + advance pointer if any fail):
   - Directory exists and is a git repo (clone it fresh from `remote:` if it doesn't exist yet — first-run bootstrap).
   - `git status --porcelain` is empty (no dirty working tree).
   - Local branch has no unpushed commits ahead of its upstream, and is not
     behind (fetch + compare) — i.e. fully in sync with remote before we start.
4. **Read backlog** (`TODO.md`):
   - If it has an unchecked item → **implement mode**, task = first unchecked item.
   - Else → **brainstorm mode**.
5. **Build prompt** from the matching template in `prompts/`, filling in the
   task text (implement mode) or repo context (brainstorm mode).
6. **Run agent**:
   ```
   cd /var/lib/cron-iterate/repos/<name> && timeout <timeout_seconds> \
     claude -p "<rendered prompt>" \
       --dangerously-skip-permissions \
       --max-turns <max_turns>
   ```
   Capture stdout/stderr to `/var/lib/cron-iterate/logs/<name>-<timestamp>.log`.
7. **Post-flight guardrail checks** against `git diff`:
   - Reject (git reset --hard to pre-run commit) if any changed path matches
     a `forbidden_paths` glob.
   - Reject if there are no changes at all (agent did nothing).
8. **Validation** (implement mode only): run `test_cmd` in the repo.
   - Pass → proceed to commit.
   - Fail → `git reset --hard` to the pre-run state, log failure, stop (no push).
9. **Commit**:
   - Implement mode: commit message summarizes the task done, references the
     TODO item text, includes `Co-Authored-By: Claude <noreply@anthropic.com>`.
   - Brainstorm mode: commit message like `chore: add N auto-iteration ideas to TODO.md`.
10. **Push** to the repo's configured branch via the deploy-key remote.
11. **Update state**: increment `last_index`, persist `state.json`.
12. **Exit 0.** Any failure path above exits non-zero after cleanup, but does
    not crash the timer (errors are caught per-repo).

## Guardrails detail

- Forbidden paths are glob-matched against every file in `git diff --name-only`
  post-run; a single match aborts the whole run for that repo (hard reset).
- The agent's `cwd` is always the target repo root under
  `/var/lib/cron-iterate/repos/` — never the tool directory itself — so
  accidental edits can't land in the automation's own code.
- `--dangerously-skip-permissions` is scoped both by that cwd convention
  *and* now by the systemd/user sandbox: even in the worst case (agent tries
  to read/write outside the repo), the OS-level isolation (`ProtectHome`,
  `ProtectSystem=strict`, dedicated UID with no access to `/home`) is the
  actual backstop, not just convention.

## Open items / assumptions to revisit later

- Assumes `claude`, `git` are reachable on `cron-iterate`'s `PATH` inside the
  hardened systemd environment (may need an explicit `Environment=PATH=...`
  in the service file since systemd services don't inherit a login shell's
  PATH).
- Network egress isn't actually restricted to Anthropic/GitHub yet (see
  "Known limitation" above) — currently relies on there being nothing else
  worth reaching from this account, not on an enforced allowlist.
- Claude Code usage from the shared credential counts against the human's
  own plan/session — no separate cost visibility for automation runs.
- No PR review step exists — commits land on the default branch unreviewed;
  revisit if this turns out to be too risky in practice.
- No max-diff-size guardrail yet (only forbidden-paths) — add if runs turn
  out to make overly large changes.

## TODO

Code (done, in this repo):

- [x] Write `lib/config.py`: load and validate `config.yaml` (repo `name`/`remote` present, `test_cmd` present, etc.), with `CRON_ITERATE_HOME` env override for local testing
- [x] Write `lib/state.py`: round-robin pointer persistence (`state.json`)
- [x] Write `lib/git_ops.py`: first-run clone bootstrap, clean/sync checks, snapshot commit hash, hard-reset-to-snapshot, commit, push
- [x] Write `lib/backlog.py`: parse `TODO.md` checklist, find first unchecked item
- [x] Write `lib/guardrails.py`: forbidden-path glob matching against changed files
- [x] Write `lib/agent.py`: construct and run the `claude -p` subprocess with `--max-turns`, capture output, enforce `timeout`
- [x] Write `prompts/implement_task.md` and `prompts/brainstorm.md` templates (explicitly instruct the agent not to run git commit/push itself)
- [x] Write `iterate.py` main entrypoint wiring the full run sequence above
- [x] Write template `config.yaml`, `requirements.txt`, `deploy.sh`, `systemd/cron-iterate.{service,timer}`
- [x] Smoke-test the full pipeline (brainstorm → implement → push, plus dirty-tree/forbidden-path/no-op abort paths) against a throwaway local repo with the agent step stubbed out — confirmed all paths behave correctly. Note: fixed `MemoryDenyWriteExecute=yes` in the systemd unit during this pass — it crashes the `claude` CLI (Node/V8 needs W+X pages for JIT), so it's been removed with a comment explaining why.

Not yet done — requires `sudo`/system changes, deliberately left for you to run or explicitly approve:

- [ ] Create the `cron-iterate` system user and `/var/lib/cron-iterate` directory tree
- [ ] Run `deploy.sh` to publish code to `/opt/cron-auto-iterate-gh` (root-owned, group-readable by `cron-iterate`)
- [ ] Fill in `config.yaml` with real target repos and copy it to `/var/lib/cron-iterate/config.yaml`
- [ ] Generate the `cron-iterate` SSH deploy key and add its public half as a write-access deploy key on each target repo
- [ ] Copy Claude Code credentials into `/var/lib/cron-iterate/.claude/`
- [ ] Install `systemd/cron-iterate.service` and `.timer` to `/etc/systemd/system/`, then `sudo systemctl enable --now cron-iterate.timer`
- [ ] Do one real end-to-end run against an actual throwaway GitHub repo (real `claude -p` invocation, real push) before pointing at real projects — the smoke test above stubbed the agent call out, so the real `claude` invocation itself is still unverified
- [ ] Verify the hardened service can actually reach `claude`/`git`/GitHub/Anthropic (`sudo systemctl start cron-iterate.service` once, check `journalctl -u cron-iterate`) — hardening directives sometimes block things surprisingly (e.g. DNS, temp files) and may need iterating on
- [ ] Decide whether to add the network egress allowlist (forward proxy) now or defer
