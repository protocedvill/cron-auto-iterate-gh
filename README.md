# cron-auto-iterate-gh

Runs headless Claude Code once a day to make one small, autonomous
improvement to a configured project, validates it, and pushes it. See
`plan.md` for the full design and rationale — this file only covers
installation.

The automation runs as a dedicated, unprivileged system user (`cron-iterate`)
with no access to your own home directory, triggered by a hardened systemd
service + timer. All commands below assume a systemd-based Linux distro
(e.g. Fedora) and are run from a clone of this repo.

## Prerequisites

- `git`, `python3` (3.10+), `rsync`
- The `claude` CLI installed and on `PATH`, already logged in under your
  own account (`claude /login` if not)
- `sudo` access
- One or more GitHub repos you want this to iterate on

## 1. Create the dedicated system user

```bash
sudo useradd --system --home-dir /var/lib/cron-iterate --create-home \
  --shell /usr/sbin/nologin cron-iterate

sudo -u cron-iterate mkdir -p /var/lib/cron-iterate/repos \
  /var/lib/cron-iterate/logs /var/lib/cron-iterate/.ssh /var/lib/cron-iterate/.claude
sudo chmod 700 /var/lib/cron-iterate/.ssh /var/lib/cron-iterate/.claude
```

## 2. Make the `claude` CLI reachable to the sandboxed service

`ProtectHome=yes` in the systemd unit hides `/home` (and `/root`,
`/run/user/*`) from the service entirely, at the kernel namespace level —
independent of file permissions. If `claude` is installed the normal way
(native installer → `~/.local/bin/claude`, a symlink into
`~/.local/share/claude/versions/<version>`), the sandboxed service can't
see it no matter what `PATH` is set to, and fails with
`FileNotFoundError: [Errno 2] No such file or directory: 'claude'`.

Fix: install a standalone copy of the actual binary somewhere outside
`/home` that the service's `PATH` (`/usr/local/bin:/usr/bin:/bin`) can
reach:

```bash
sudo install -o root -g root -m 755 \
  "$(readlink -f "$(command -v claude)")" /usr/local/bin/claude
```

This is a one-time copy, not a symlink, so it keeps working even though
the source is hidden from the sandboxed process. It won't auto-update when
your personal `claude` CLI does — that's arguably a feature for a daily
unattended job (no surprise breakage from an upstream update), but re-run
the command above whenever you deliberately want the automation to pick up
a newer CLI version.

## 3. Deploy the tool's code

From your clone of this repo:

```bash
./deploy.sh
```

This rsyncs `iterate.py`, `lib/`, and `prompts/` to `/opt/cron-auto-iterate-gh`,
owned by `root:cron-iterate` with mode `750` — readable/executable by the
service user, writable only by root. Re-run this any time you change the
tool's code.

Install Python dependencies where `python3` on the system can see them:

```bash
sudo pip install -r requirements.txt
```

## 4. Configure target repos

Copy the template and edit it:

```bash
sudo cp config.yaml /var/lib/cron-iterate/config.yaml
sudo "$EDITOR" /var/lib/cron-iterate/config.yaml
sudo chown cron-iterate:cron-iterate /var/lib/cron-iterate/config.yaml
```

Fill in each repo's `name` and `remote` (SSH URL), and a `test_cmd` if the
project has one (strongly recommended — this gates every push). See the
comments in `config.yaml` and the "Configuration format" section of
`plan.md` for all fields.

## 5. Set up git push credentials

Generate a single SSH keypair for the automation user:

```bash
sudo -u cron-iterate ssh-keygen -t ed25519 -f /var/lib/cron-iterate/.ssh/id_ed25519 -N ""
sudo -u cron-iterate cat /var/lib/cron-iterate/.ssh/id_ed25519.pub
```

For **each** target repo, add that public key on GitHub as a **Deploy key**
with **write access**: repo → Settings → Deploy keys → Add deploy key.
Reusing the same keypair across repos is fine — GitHub still scopes access
per-repo, so a leak only affects repos where you explicitly added it.

Add GitHub to the automation user's known hosts so the first clone/push
doesn't hang on a host-key prompt:

```bash
sudo -u cron-iterate bash -c 'ssh-keyscan github.com >> /var/lib/cron-iterate/.ssh/known_hosts'
```

## 6. Set up Claude Code credentials

Copy your own credentials into the automation user's home (this shares your
existing login/subscription — usage isn't tracked separately):

```bash
sudo cp ~/.claude/.credentials.json /var/lib/cron-iterate/.claude/.credentials.json
sudo chown -R cron-iterate:cron-iterate /var/lib/cron-iterate/.claude
sudo chmod 600 /var/lib/cron-iterate/.claude/.credentials.json
```

## 7. Install and enable the systemd timer

```bash
sudo cp systemd/cron-iterate.service systemd/cron-iterate.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cron-iterate.timer
```

This runs `iterate.py` once daily (±30 min random delay) as `cron-iterate`,
sandboxed with `ProtectHome=yes`, `ProtectSystem=strict`, and related
hardening directives (see `plan.md` → "Isolation & sandboxing" for what
each one does and why).

## 8. Verify it works

Trigger one run manually and watch it:

```bash
sudo systemctl start cron-iterate.service
journalctl -u cron-iterate -f
```

Since target repos start with no `TODO.md`, the first run per repo will be
a **brainstorm** run (adds ideas to `TODO.md`, commits, exits) rather than
an implementation run — that's expected. The next scheduled run for that
repo will pick the first idea and implement it.

Check `/var/lib/cron-iterate/logs/` for the raw `claude` transcript of each
run, and `git log` on the target repo for the actual commits pushed.

## Debugging

Every run logs a version line first, e.g.:

```
iterate.py sha256=5300ced274c5 path=/opt/cron-auto-iterate-gh/iterate.py | commit=e4da4a6 deployed_at=2026-07-01T15:02:30Z
```

That's always visible with plain `journalctl -u cron-iterate` (no `sudo`
needed to read the journal, unlike `/opt` itself), and directly answers
"am I running stale code?": compare `commit=` against `git log -1` in your
dev clone, or the `sha256=` against `sha256sum iterate.py` there. A
`+uncommitted-changes` suffix means `deploy.sh` was run against a dirty
dev tree. If you forgot to run `./deploy.sh` after an edit, this is the
line that tells you.

The very next log line every run always prints which `config.yaml` it
actually loaded and which repos it found in it, e.g.:

```
config: /var/lib/cron-iterate/config.yaml (repos: real-repo-a, real-repo-b)
```

This matters because **`deploy.sh` never touches `config.yaml`** (on
purpose, so editing the live config on the server doesn't get clobbered by
a code redeploy) — the copy in this dev repo and
`/var/lib/cron-iterate/config.yaml` are two independent files that don't
sync automatically. If this line lists repos you don't recognize or
expect, you edited the wrong copy; re-sync with:

```bash
sudo cp config.yaml /var/lib/cron-iterate/config.yaml
sudo chown cron-iterate:cron-iterate /var/lib/cron-iterate/config.yaml
```

For anything else, run the read-only diagnostic instead of waiting for the
timer or digging through `journalctl`:

```bash
sudo -u cron-iterate python3 /opt/cron-auto-iterate-gh/iterate.py --check           # all repos
sudo -u cron-iterate python3 /opt/cron-auto-iterate-gh/iterate.py --check --repo NAME # one repo
```

It reports, without touching anything except a `git fetch`: whether the
repo is cloned yet, its branch, the exact `git status --porcelain` output
if the working tree is dirty, ahead/behind counts vs. `origin`, and the
next backlog item (or "will brainstorm"). This is the fastest way to find
out *why* a run keeps aborting instead of guessing from the one-line log
message.

Add `-v`/`--verbose` to either a real run or `--check` for full DEBUG-level
tracing of every git command executed (command, cwd, exit code,
stdout/stderr) — useful when even `--check`'s report doesn't explain the
behavior:

```bash
sudo -u cron-iterate python3 /opt/cron-auto-iterate-gh/iterate.py --check -v
```

## Troubleshooting

- **It's iterating on repos I didn't expect / doesn't see my config
  changes**: you almost certainly edited `config.yaml` in this dev repo
  and expected `./deploy.sh` to pick it up — it doesn't (see "Debugging"
  above). Check the `config: ...` log line, and if needed, `sudo cp
  config.yaml /var/lib/cron-iterate/config.yaml`.
- **`Permission ... denied to deploy key` on push, for a repo name you
  don't recognize**: the clone's `origin` was set the first time it was
  cloned and is never updated automatically. If you changed a repo's
  `remote:` in `config.yaml` *after* it was already cloned once, the local
  clone keeps pushing to the old remote forever. `iterate.py --check` flags
  this as a `remote: MISMATCH`. Fix: `sudo rm -rf
  /var/lib/cron-iterate/repos/<name>` to let it re-clone from the current
  `remote:`.
- **`working tree is not clean` keeps happening even right after a fresh
  clone**: run `--check` on that repo to see the exact dirty files. If a
  previous run crashed with an exception the code didn't anticipate
  (rather than a normal validation/guardrail failure), older versions of
  `iterate.py` could leave the clone dirty forever - redeploy the latest
  code (`./deploy.sh`) and delete the stuck clone
  (`sudo rm -rf /var/lib/cron-iterate/repos/<name>`) to let it re-clone
  cleanly on the next run.
- **`FileNotFoundError: [Errno 2] No such file or directory: 'claude'`**:
  `claude` is installed under your home directory and `ProtectHome=yes`
  hides all of `/home` from the sandboxed service — see step 2.
- **Service fails immediately / `SIGSYS` from claude**: a systemd hardening
  directive is blocking something `claude` (a Node/V8 process) needs.
  `journalctl -u cron-iterate` will show the syscall/violation; the unit
  file already avoids `MemoryDenyWriteExecute` for this reason, but you may
  need to relax `SystemCallFilter` similarly if you hit it elsewhere.
- **Can't resolve DNS / clone fails**: `ProtectSystem=strict` and friends
  don't block networking, but double-check `/etc/resolv.conf` is reachable
  under the sandbox (it usually is; some minimal container-like setups
  differ).
- **`git push` hangs**: usually a missing `known_hosts` entry — see step 5.
- **`fatal: unable to auto-detect email address` / `Author identity
  unknown`**: shouldn't happen — commits always pass an explicit identity
  via `git -c user.name=... -c user.email=...` (see `committer_name`/
  `committer_email` in `config.yaml`), specifically so the `cron-iterate`
  account never needs its own `git config --global` setup. If you see this,
  you're running code from before that fix — redeploy (`./deploy.sh`) and
  check the version line in the journal.
- **Run aborts with "working tree is not clean" / "not in sync with
  origin"**: by design — the tool refuses to touch a repo clone that isn't
  in a known-good state. Check `/var/lib/cron-iterate/repos/<name>`
  manually; a previous run may have failed mid-way and left it dirty.

## Updating

- Tool code: edit in this repo, then re-run `./deploy.sh`.
- Config: edit `/var/lib/cron-iterate/config.yaml` directly (or edit
  `config.yaml` here and re-copy it — it isn't touched by `deploy.sh`).
- After either, no restart is needed — `iterate.py` is invoked fresh by
  each timer tick.

## Uninstalling

```bash
./uninstall.sh
```

By default this stops/disables the timer, removes the systemd units, and
deletes the deployed code in `/opt/cron-auto-iterate-gh` — the pure
"installation" artifacts. It deliberately **leaves in place**
`/var/lib/cron-iterate` (repo clones, `TODO.md` history, `state.json`, the
SSH deploy key, and the copied Claude credentials) and the `cron-iterate`
system user, since those hold state/credentials you may still want.

To remove everything:

```bash
./uninstall.sh --purge-data --remove-user   # prompts before each destructive step
./uninstall.sh --remove-user -y             # same, no prompts (non-interactive)
```

It also prints a reminder to manually revoke the GitHub deploy key from
each configured repo (Settings → Deploy keys) — this script only touches
the local machine, not GitHub.
