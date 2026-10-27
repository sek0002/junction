# Home server deployment

Run Junction on a Linux server with systemd and Python 3.10 or newer. The service starts at boot and restarts after a failure. No Node.js runtime is needed.

The installer chooses an available random port **once** and persists it. Reboots keep the same port and browser URL. You can also choose any unused non-privileged port yourself.

## Install

On Debian/Ubuntu:

```sh
sudo apt update
sudo apt install -y git python3 python3-venv
sudo git clone https://github.com/sek0002/junction.git /opt/junction
cd /opt/junction
sudo bash scripts/install-systemd.sh
```

On another distribution, install equivalent Git, Python and venv packages, then use the same clone and installer commands. The checkout must be `/opt/junction` for the supplied unit.

The installer creates a dedicated `junction` service account, installs Python dependencies into `/opt/junction/.venv`, writes `/etc/systemd/system/junction.service`, and enables the service. Re-running it preserves the existing environment file. It does not copy your development database to the server.

Read the chosen port and service status:

```sh
sudo cat /etc/junction/junction.env
sudo systemctl status junction --no-pager
sudo journalctl -u junction -n 50 --no-pager
```

The initial binding is `127.0.0.1`. For example, if the file shows port **48173**, open a tunnel from your computer:

```sh
ssh -L 8765:127.0.0.1:48173 YOUR_USER@YOUR_SERVER
```

Leave that SSH session open and visit **http://127.0.0.1:8765** on your computer. Read the private first-run PIN on the server:

```sh
sudo cat /var/lib/junction/golden_gate.initial-admin-pin
```

Sign in as **admin** using that generated PIN, then use the profile icon → Change PIN. Create other accounts under Users. New installations have no shared default credential; upgrading an existing database keeps its accounts and PINs.

For a specific port on a fresh installation:

```sh
sudo bash scripts/install-systemd.sh --port 48173
```

The availability check is a snapshot; if another application takes the chosen port before startup, choose a different port in the environment file and restart Junction.

## Access from the home network

After setting your admin PIN, edit the configuration:

```sh
sudoedit /etc/junction/junction.env
```

Set `GOLDEN_GATE_HOST=0.0.0.0` and retain your chosen port, then:

```sh
sudo systemctl restart junction
```

Open **http://YOUR_SERVER_LAN_IP:YOUR_PORT**. Allow that TCP port from your home subnet in your server firewall if needed. The app does not change your firewall or router settings.

For mobile installation/PWA support, use an HTTPS reverse proxy on your home network. Keep Junction bound to `127.0.0.1` if the proxy runs on the same server, and proxy to the chosen port. Preserve the original Host header and set `X-Forwarded-Proto`; this keeps same-origin writes and HTTPS session cookies working. Only trusted proxy addresses belong in `GOLDEN_GATE_FORWARDED_ALLOW_IPS`; its default trusts local proxies. Junction should be served at the URL root, not a subpath.

## Settings

`/etc/junction/junction.env`:

```ini
GOLDEN_GATE_HOST=127.0.0.1
GOLDEN_GATE_PORT=48173
GOLDEN_GATE_DB=/var/lib/junction/golden_gate.sqlite3
GOLDEN_GATE_FORWARDED_ALLOW_IPS=127.0.0.1,::1
```

Changes take effect after `sudo systemctl restart junction`. Systemd reads this file directly; it is not Uvicorn's `--env-file` option.

To request a new OS-assigned port on **every** start, set `GOLDEN_GATE_PORT=0`. Find the actual port in `sudo journalctl -u junction -b`. Use the installer's default persistent random port when you want a stable URL or reverse-proxy target.

The service uses one Uvicorn process and no development reloader. SQLite and its containing directory remain writable by the service; application code is read-only to it.

## Data and backups

`/var/lib/junction/golden_gate.sqlite3` contains the shared library, accounts, activity, private sandboxes and comparison sources/results. It is separate from the Git checkout and survives service restarts and code updates. A new database is initialized with the bundled current plate maps and backbone examples.

For a complete, consistent backup:

```sh
sudo systemctl stop junction
sudo install -d -m 0700 /var/backups/junction
sudo cp -a /var/lib/junction "/var/backups/junction/$(date +%Y%m%d-%H%M%S)"
sudo systemctl start junction
```

To restore, stop Junction, replace `/var/lib/junction` with the saved directory, set its owner to `junction:junction`, then start the service. This also restores the accounts and sandboxes from that backup.

To migrate your existing local database, stop its app and this service, transfer the SQLite file privately using SSH/SCP, and place it at `/var/lib/junction/golden_gate.sqlite3`. If using a custom `.sources.json` manifest, transfer its referenced source files as well, retaining their relative paths. Then:

```sh
sudo chown -R junction:junction /var/lib/junction
sudo chmod 0700 /var/lib/junction
sudo chmod 0600 /var/lib/junction/golden_gate.sqlite3
sudo systemctl start junction
```

Keep database files and backups out of the public repository. The supplied `.gitignore` excludes them.

## Update

Back up the data first. Then:

```sh
sudo systemctl stop junction
sudo git -C /opt/junction pull --ff-only
sudo /opt/junction/.venv/bin/python -m pip install -r /opt/junction/requirements.txt
sudo systemctl start junction
sudo systemctl status junction --no-pager
```

After a service-unit change, reinstall that unit before starting:

```sh
sudo install -m 0644 /opt/junction/deploy/junction.service /etc/systemd/system/junction.service
sudo systemctl daemon-reload
sudo systemctl restart junction
```

Refresh browser tabs to load updated assets. The existing database is migrated in place; restarting does not reset accounts, PINs or user sandboxes.

## Troubleshooting

```sh
sudo journalctl -u junction -f
sudo systemctl restart junction
sudo systemctl stop junction
sudo systemctl disable --now junction
```

- **Address already in use:** choose a free port in `/etc/junction/junction.env` and restart.
- **Permission denied / read-only database:** check ownership of `/var/lib/junction` and the database path in the environment file. Keep writable data under `/var/lib/junction`, which the service unit permits.
- **Cannot connect from another computer:** use the SSH tunnel or set the LAN bind address, and check the server firewall.
- **403 after putting a proxy in front:** preserve the original Host header and forwarded HTTPS scheme; configure the proxy's actual address in `GOLDEN_GATE_FORWARDED_ALLOW_IPS`.

## References

- [Uvicorn settings](https://uvicorn.dev/settings/): host, port 0, proxy headers and worker configuration.
- [systemd service units](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html): process startup and restart behavior.
- [systemd execution settings](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html): environment files, state directories and service filesystem permissions.
