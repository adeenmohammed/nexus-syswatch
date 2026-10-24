# NEXUS // SYSWATCH — Terminal Edition

A green, hacker-style full-screen Linux system monitor that runs **inside your terminal**. It inspects the actual machine on which it runs using `psutil`; it does not need a browser, localhost web page, FastAPI server, or root privileges for normal monitoring.

## Quick start (Linux Mint / Ubuntu)

```bash
sudo apt update
sudo apt install -y python3 python3-venv
unzip nexus-syswatch-terminal.zip
cd nexus-syswatch
./scripts/install-terminal.sh
./scripts/terminal.sh
```

The installer creates an isolated Python environment and installs `psutil`. It does not use `sudo` to run the monitor. `sudo apt` is only for installing the system Python packages.

## Controls

| Key | Action |
|---|---|
| `1` | Overview: CPU, RAM, swap, root filesystem, network throughput |
| `2` | Processes: live process list, CPU/RAM, PID, user, state |
| `3` | Network: interfaces, link status, RX/TX counters and throughput |
| `4` | Storage: mounted filesystems and disk I/O counters |
| `5` | System: hostname, distribution, kernel, CPU, RAM, uptime and load |
| `Space` | Pause/resume live refresh |
| `r` | Refresh now |
| `/` or `f` | Search processes by name or PID (Processes view) |
| `c` | Clear process search |
| `s` | Cycle process sort: CPU → memory → PID → name |
| `v` | Cycle process state filter |
| `↑` / `↓` or `k` / `j` | Move selection in process list |
| `n` / `p` | Next/previous process page |
| `?` | Show keyboard help in the status line |
| `q` | Quit |

## What it measures

- CPU percentage and logical core count
- RAM, available memory, swap and root filesystem usage
- Network throughput calculated from changes in byte counters over elapsed time
- Per-interface status and cumulative RX/TX counters
- Filesystem mounts and disk I/O counters
- Hostname, OS/kernel, architecture, Python version, uptime, load average, CPU frequency and process count
- Process IDs, names, users, states, CPU usage and resident memory

Values are collected from the host OS. CPU percentages and throughput need a sampling interval, so the first network speed sample is zero. Some process details or mount points may be unavailable due to permissions or system state.

## Safety

- Runs as the current user; do **not** run it with `sudo`.
- Process listing is read-only. There is intentionally no kill-process button.
- Does not execute shell commands from user input.
- Does not expose a network service or send metrics anywhere.
- Process CPU values are per-process measurements since the last sample and can be noisy for short-lived processes.

## Development notes

The original web dashboard remains in `frontend/` and the FastAPI backend remains in `backend/app/main.py`. To use the terminal edition, run `./scripts/terminal.sh`; no local web server is started. The terminal UI is implemented in `backend/app/terminal.py` using Python's standard `curses` library and `psutil`.

## Troubleshooting

- If the screen is too small, maximize the terminal (minimum 70 columns × 18 rows).
- If arrow keys do not work, use `j` and `k` in the Processes view.
- If colors are missing, use a terminal that supports ANSI colors and set `TERM` appropriately (commonly `xterm-256color`).
- If `venv` creation fails, install `python3-venv` with your distribution package manager.
