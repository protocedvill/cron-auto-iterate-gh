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

## 2. Deploy the tool's code

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

## 3. Configure target repos

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

## 4. Set up git push credentials

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

## 5. Set up Claude Code credentials

Copy your own credentials into the automation user's home (this shares your
existing login/subscription — usage isn't tracked separately):

```bash
sudo cp ~/.claude/.credentials.json /var/lib/cron-iterate/.claude/.credentials.json
sudo chown -R cron-iterate:cron-iterate /var/lib/cron-iterate/.claude
sudo chmod 600 /var/lib/cron-iterate/.claude/.credentials.json
```

## 6. Install and enable the systemd timer

```bash
sudo cp systemd/cron-iterate.service systemd/cron-iterate.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cron-iterate.timer
```

This runs `iterate.py` once daily (±30 min random delay) as `cron-iterate`,
sandboxed with `ProtectHome=yes`, `ProtectSystem=strict`, and related
hardening directives (see `plan.md` → "Isolation & sandboxing" for what
each one does and why).

## 7. Verify it works

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

## Troubleshooting

- **Service fails immediately / `SIGSYS` from claude**: a systemd hardening
  directive is blocking something `claude` (a Node/V8 process) needs.
  `journalctl -u cron-iterate` will show the syscall/violation; the unit
  file already avoids `MemoryDenyWriteExecute` for this reason, but you may
  need to relax `SystemCallFilter` similarly if you hit it elsewhere.
- **Can't resolve DNS / clone fails**: `ProtectSystem=strict` and friends
  don't block networking, but double-check `/etc/resolv.conf` is reachable
  under the sandbox (it usually is; some minimal container-like setups
  differ).
- **`git push` hangs**: usually a missing `known_hosts` entry — see step 4.
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
