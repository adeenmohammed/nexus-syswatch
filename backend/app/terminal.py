"""NEXUS // SYSWATCH — full-screen Linux terminal monitor.

Uses psutil to inspect the host running this process. No web server or browser required.
"""
from __future__ import annotations

import curses
import os
import platform
import shutil
import socket
import time
from datetime import datetime
from typing import Any

import psutil

APP_NAME = "NEXUS // SYSWATCH"
GREEN = 2
DIM_GREEN = 3
CYAN = 4
YELLOW = 5
RED = 6
WHITE = 7

def fmt_bytes(value: float) -> str:
    value = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:,.1f} {unit}"
        value /= 1024
    return f"{value:,.1f} TB"

def fmt_rate(value: float) -> str:
    return f"{fmt_bytes(value)}/s"

def safe_add(win, y: int, x: int, text: str, attr: int = 0, max_width: int | None = None):
    try:
        height, width = win.getmaxyx()
        if y < 0 or y >= height or x >= width:
            return
        available = max(0, width - x - 1)
        if max_width is not None:
            available = min(available, max_width)
        if available:
            win.addnstr(y, x, str(text).replace("\n", " "), available, attr)
    except curses.error:
        pass

def bar(percent: float, width: int = 20) -> str:
    percent = max(0.0, min(100.0, float(percent)))
    filled = int(width * percent / 100)
    return "█" * filled + "░" * (width - filled)

def init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(GREEN, curses.COLOR_GREEN, -1)
    curses.init_pair(DIM_GREEN, curses.COLOR_GREEN, -1)
    curses.init_pair(CYAN, curses.COLOR_CYAN, -1)
    curses.init_pair(YELLOW, curses.COLOR_YELLOW, -1)
    curses.init_pair(RED, curses.COLOR_RED, -1)
    curses.init_pair(WHITE, curses.COLOR_WHITE, -1)

def color_for(percent: float) -> int:
    if percent >= 90:
        return curses.color_pair(RED) | curses.A_BOLD
    if percent >= 75:
        return curses.color_pair(YELLOW) | curses.A_BOLD
    return curses.color_pair(GREEN)

def get_processes(sort_key: str, reverse: bool, query: str, state_filter: str):
    rows = []
    for proc in psutil.process_iter(["pid", "name", "username", "status", "memory_info", "create_time"]):
        try:
            info = proc.info
            # Prime CPU measurement; next refresh provides a meaningful percentage.
            cpu = proc.cpu_percent(interval=None)
            rss = info["memory_info"].rss if info.get("memory_info") else 0
            name = info.get("name") or "?"
            status = info.get("status") or "?"
            pid = info.get("pid") or 0
            username = info.get("username") or "?"
            if query and query not in name.lower() and query not in str(pid):
                continue
            if state_filter != "ALL" and status.upper() != state_filter:
                continue
            rows.append({
                "pid": pid, "name": name[:32], "user": username[:16],
                "status": status, "cpu": cpu, "rss": rss,
                "started": info.get("create_time"),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
            continue
    key_map = {
        "CPU": lambda p: p["cpu"],
        "MEM": lambda p: p["rss"],
        "PID": lambda p: p["pid"],
        "NAME": lambda p: p["name"].lower(),
    }
    rows.sort(key=key_map[sort_key], reverse=reverse)
    return rows

def draw_box(stdscr, y, x, h, w, title):
    if h < 2 or w < 3:
        return
    attr = curses.color_pair(DIM_GREEN)
    try:
        stdscr.addstr(y, x, "┌" + "─" * (w - 2) + "┐", attr)
        for row in range(1, h - 1):
            stdscr.addstr(y + row, x, "│", attr)
            stdscr.addstr(y + row, x + w - 1, "│", attr)
        stdscr.addstr(y + h - 1, x, "└" + "─" * (w - 2) + "┘", attr)
        if title:
            safe_add(stdscr, y, x + 2, f" {title} ", curses.color_pair(GREEN) | curses.A_BOLD, w - 4)
    except curses.error:
        pass

def draw_overview(stdscr, metrics: dict[str, Any], start_y: int):
    height, width = stdscr.getmaxyx()
    gap = 2
    col_w = max(25, (width - 6) // 2)
    box_h = 6
    cards = [
        ("CPU", metrics["cpu"], f'{metrics["cores"]} logical cores'),
        ("MEMORY", metrics["memory"], f'{fmt_bytes(metrics["mem_used"])} / {fmt_bytes(metrics["mem_total"])}'),
        ("SWAP", metrics["swap"], f'{fmt_bytes(metrics["swap_used"])} / {fmt_bytes(metrics["swap_total"])}'),
        ("ROOT FILESYSTEM", metrics["disk"], f'{fmt_bytes(metrics["disk_used"])} / {fmt_bytes(metrics["disk_total"])}'),
    ]
    for i, (name, pct, detail) in enumerate(cards):
        x = 2 + (i % 2) * (col_w + gap)
        y = start_y + (i // 2) * (box_h + 1)
        draw_box(stdscr, y, x, box_h, min(col_w, width - x - 1), name)
        safe_add(stdscr, y + 1, x + 2, f"{pct:5.1f}%", color_for(pct))
        safe_add(stdscr, y + 2, x + 2, bar(pct, min(23, max(8, col_w - 15))), curses.color_pair(GREEN))
        safe_add(stdscr, y + 3, x + 2, detail, curses.color_pair(WHITE), col_w - 4)
    net_y = start_y + 2 * (box_h + 1)
    draw_box(stdscr, net_y, 2, 5, width - 4, "NETWORK THROUGHPUT")
    safe_add(stdscr, net_y + 1, 4, f"↓ DOWNLOAD  {fmt_rate(metrics['down'])}", curses.color_pair(CYAN) | curses.A_BOLD)
    safe_add(stdscr, net_y + 2, 4, f"↑ UPLOAD    {fmt_rate(metrics['up'])}", curses.color_pair(GREEN) | curses.A_BOLD)
    safe_add(stdscr, net_y + 3, 4, f"Interfaces: {metrics['interfaces']}   |   Packets received: {metrics['packets_recv']:,}   sent: {metrics['packets_sent']:,}", curses.color_pair(WHITE))

def draw_processes(stdscr, rows, start_y, page, selected, query, sort_key, state_filter):
    height, width = stdscr.getmaxyx()
    safe_add(stdscr, start_y, 2, f"FILTER: {query or '(none)'}   STATE: {state_filter}   SORT: {sort_key}", curses.color_pair(CYAN))
    header_y = start_y + 2
    cols = [
        ("PID", 7), ("CPU%", 8), ("MEMORY", 12), ("USER", 14), ("STATE", 12), ("PROCESS", max(12, width - 62))
    ]
    x = 2
    for label, size in cols:
        safe_add(stdscr, header_y, x, label, curses.color_pair(GREEN) | curses.A_BOLD, size)
        x += size
    safe_add(stdscr, header_y + 1, 2, "─" * max(1, width - 4), curses.color_pair(DIM_GREEN))
    visible = max(1, height - header_y - 5)
    offset = page * visible
    for idx, proc in enumerate(rows[offset:offset + visible]):
        y = header_y + 2 + idx
        attr = curses.color_pair(GREEN)
        if idx == selected:
            attr = curses.color_pair(curses.COLOR_BLACK) | curses.A_REVERSE
        x = 2
        values = [
            (str(proc["pid"]), 7),
            (f'{proc["cpu"]:5.1f}', 8),
            (fmt_bytes(proc["rss"]), 12),
            (proc["user"], 14),
            (proc["status"][:11], 12),
            (proc["name"], max(12, width - 62)),
        ]
        for value, size in values:
            safe_add(stdscr, y, x, value, attr, size - 1)
            x += size
    safe_add(stdscr, height - 3, 2, f"{len(rows)} processes matched · Page {page + 1}", curses.color_pair(DIM_GREEN))

def collect_metrics(previous_net, previous_time):
    now = time.monotonic()
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()
    elapsed = max(0.001, now - previous_time) if previous_time is not None else 0
    down = max(0, net.bytes_recv - previous_net.bytes_recv) / elapsed if previous_net and elapsed else 0
    up = max(0, net.bytes_sent - previous_net.bytes_sent) / elapsed if previous_net and elapsed else 0
    try:
        load = os.getloadavg()
        load_text = " / ".join(f"{v:.2f}" for v in load)
    except (AttributeError, OSError):
        load_text = "unavailable"
    try:
        freq = psutil.cpu_freq()
        freq_text = f"{freq.current:.0f} MHz" if freq else "unavailable"
    except (AttributeError, OSError):
        freq_text = "unavailable"
    metrics = {
        "cpu": cpu, "cores": psutil.cpu_count() or 1,
        "memory": mem.percent, "mem_used": mem.used, "mem_total": mem.total,
        "swap": swap.percent, "swap_used": swap.used, "swap_total": swap.total,
        "disk": disk.percent, "disk_used": disk.used, "disk_total": disk.total,
        "down": down, "up": up, "interfaces": len(psutil.net_if_stats()),
        "packets_recv": net.packets_recv, "packets_sent": net.packets_sent,
        "uptime": max(0, int(time.time() - psutil.boot_time())),
        "load": load_text, "freq": freq_text,
    }
    return metrics, net, now

def human_uptime(seconds: int) -> str:
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    return f"{days}d {hours}h {minutes}m"

def app(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)
    init_colors()
    curses.use_default_colors()
    try:
        curses.set_escdelay(25)
    except Exception:
        pass
    # Prime psutil CPU counters so the first display isn't misleading.
    psutil.cpu_percent(interval=None)
    previous_net = None
    previous_time = None
    metrics = {}
    page = 0
    selected = 0
    active_view = "OVERVIEW"
    sort_key = "CPU"
    reverse = True
    state_filter = "ALL"
    query = ""
    filter_mode = False
    paused = False
    last_refresh = 0.0
    processes = []
    notice = "Ready. Monitoring this host directly; no web server required."
    while True:
        now = time.monotonic()
        if not paused and now - last_refresh >= 1.0:
            metrics, previous_net, previous_time = collect_metrics(previous_net, previous_time)
            processes = get_processes(sort_key, reverse, query.lower(), state_filter)
            last_refresh = now
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        if height < 18 or width < 70:
            safe_add(stdscr, 1, 2, "NEXUS // SYSWATCH needs a terminal at least 70 columns × 18 rows.", curses.color_pair(RED) | curses.A_BOLD)
            safe_add(stdscr, 3, 2, f"Current size: {width} × {height}. Maximize terminal or press q to quit.", curses.color_pair(GREEN))
            stdscr.refresh()
            key = stdscr.getch()
            if key in (ord("q"), ord("Q")):
                break
            time.sleep(0.1)
            continue

        title = " N E X U S  //  S Y S W A T C H "
        safe_add(stdscr, 0, max(1, (width - len(title)) // 2), title, curses.color_pair(GREEN) | curses.A_BOLD)
        status = "● LIVE" if not paused else "Ⅱ PAUSED"
        safe_add(stdscr, 2, 2, f"{status}  {socket.gethostname()}  |  {platform.system()} {platform.release()}", curses.color_pair(GREEN if not paused else YELLOW) | curses.A_BOLD)
        safe_add(stdscr, 2, width - 23, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), curses.color_pair(DIM_GREEN))
        tabs = "[1] OVERVIEW  [2] PROCESSES  [3] NETWORK  [4] STORAGE  [5] SYSTEM"
        safe_add(stdscr, 4, 2, tabs, curses.color_pair(CYAN) | curses.A_BOLD)
        safe_add(stdscr, 5, 2, "═" * (width - 4), curses.color_pair(DIM_GREEN))
        if active_view == "OVERVIEW" and metrics:
            draw_overview(stdscr, metrics, 7)
            safe_add(stdscr, height - 5, 2, f"UPTIME {human_uptime(metrics['uptime'])}  LOAD {metrics['load']}  CPU FREQ {metrics['freq']}", curses.color_pair(WHITE))
        elif active_view == "PROCESSES":
            draw_processes(stdscr, processes, 7, page, selected, query, sort_key, state_filter)
            safe_add(stdscr, height - 5, 2, "s sort  f filter  / search  ↑↓ select  n/p page  c clear search", curses.color_pair(WHITE))
            if processes:
                proc = processes[min(page * max(1, height - 14) + selected, len(processes)-1)]
                safe_add(stdscr, height - 4, 2, f"Selected PID {proc['pid']} · {proc['name']} · {proc['cpu']:.1f}% CPU · {fmt_bytes(proc['rss'])} RAM", curses.color_pair(YELLOW))
        elif active_view == "NETWORK":
            draw_box(stdscr, 7, 2, height - 11, width - 4, "NETWORK INTERFACES")
            y = 9
            counters = psutil.net_io_counters(pernic=True)
            stats = psutil.net_if_stats()
            for name, counter in counters.items():
                st = stats.get(name)
                line = f"{name[:18]:18} {'UP' if st and st.isup else 'DOWN':4}  RX {fmt_bytes(counter.bytes_recv):>12}  TX {fmt_bytes(counter.bytes_sent):>12}  RX packets {counter.packets_recv:>10,}  TX packets {counter.packets_sent:>10,}"
                safe_add(stdscr, y, 4, line, curses.color_pair(GREEN if st and st.isup else DIM_GREEN))
                y += 1
                if y >= height - 5: break
            safe_add(stdscr, height - 5, 2, f"Current throughput  ↓ {fmt_rate(metrics.get('down', 0))}   ↑ {fmt_rate(metrics.get('up', 0))}", curses.color_pair(CYAN) | curses.A_BOLD)
        elif active_view == "STORAGE":
            draw_box(stdscr, 7, 2, height - 11, width - 4, "FILESYSTEMS")
            y = 9
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    line = f"{part.device[:18]:18} {part.mountpoint[:18]:18} {usage.percent:5.1f}%  {bar(usage.percent, 16)}  {fmt_bytes(usage.used)} / {fmt_bytes(usage.total)}"
                    safe_add(stdscr, y, 4, line, color_for(usage.percent))
                    y += 1
                    if y >= height - 5: break
                except (PermissionError, OSError):
                    continue
            io = psutil.disk_io_counters()
            if io:
                safe_add(stdscr, height - 5, 2, f"Disk I/O  READ {fmt_bytes(io.read_bytes)} total  WRITE {fmt_bytes(io.write_bytes)} total", curses.color_pair(WHITE))
        elif active_view == "SYSTEM":
            draw_box(stdscr, 7, 2, height - 11, width - 4, "HOST INFORMATION")
            info = [
                ("Hostname", socket.gethostname()),
                ("Operating system", f"{platform.system()} {platform.release()}"),
                ("Distribution", " ".join(platform.freedesktop_os_release().get(k, "") for k in ("NAME", "VERSION")) if hasattr(platform, "freedesktop_os_release") else platform.platform()),
                ("Architecture", platform.machine()),
                ("Python", platform.python_version()),
                ("CPU cores", str(psutil.cpu_count(logical=False) or "?") + " physical / " + str(psutil.cpu_count(logical=True) or "?") + " logical"),
                ("CPU frequency", metrics.get("freq", "unavailable")),
                ("RAM", fmt_bytes(psutil.virtual_memory().total)),
                ("Uptime", human_uptime(metrics.get("uptime", 0))),
                ("Load average", metrics.get("load", "unavailable")),
                ("Boot time", datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")),
                ("PID count", str(len(psutil.pids()))),
            ]
            for idx, (label, value) in enumerate(info):
                safe_add(stdscr, 9 + idx, 4, f"{label:<20}", curses.color_pair(CYAN))
                safe_add(stdscr, 9 + idx, 26, value, curses.color_pair(WHITE))
        safe_add(stdscr, height - 2, 2, notice[:max(1, width - 4)], curses.color_pair(DIM_GREEN))
        footer = "q quit  space pause/resume  r refresh  1-5 views  ? help"
        safe_add(stdscr, height - 1, 2, footer, curses.color_pair(GREEN) | curses.A_BOLD)
        stdscr.refresh()

        key = stdscr.getch()
        if key == -1:
            time.sleep(0.08)
            continue
        if filter_mode:
            if key in (10, 13, curses.KEY_ENTER):
                filter_mode = False
                page = selected = 0
                notice = f"Process filter set to: {query or '(none)'}"
            elif key in (27,):
                filter_mode = False
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                query = query[:-1]
                processes = get_processes(sort_key, reverse, query.lower(), state_filter)
            elif 32 <= key <= 126:
                query += chr(key)
                processes = get_processes(sort_key, reverse, query.lower(), state_filter)
            continue
        if key in (ord("q"), ord("Q")):
            break
        elif key in (ord(" "),):
            paused = not paused
            notice = "Monitoring paused." if paused else "Monitoring resumed."
        elif key in (ord("r"), ord("R")):
            last_refresh = 0
            notice = "Manual refresh requested."
        elif key == ord("1"): active_view = "OVERVIEW"
        elif key == ord("2"): active_view = "PROCESSES"
        elif key == ord("3"): active_view = "NETWORK"
        elif key == ord("4"): active_view = "STORAGE"
        elif key == ord("5"): active_view = "SYSTEM"
        elif key in (ord("/"), ord("f"), ord("F")) and active_view == "PROCESSES":
            filter_mode = True
            notice = "Type process name or PID, then Enter. Esc cancels."
        elif key in (ord("c"), ord("C")) and active_view == "PROCESSES":
            query = ""
            page = selected = 0
            notice = "Process search cleared."
        elif key in (ord("s"), ord("S")) and active_view == "PROCESSES":
            sort_key = {"CPU": "MEM", "MEM": "PID", "PID": "NAME", "NAME": "CPU"}[sort_key]
            processes = get_processes(sort_key, reverse, query.lower(), state_filter)
            notice = f"Processes sorted by {sort_key}."
        elif key == ord("v") and active_view == "PROCESSES":
            state_filter = {"ALL": "RUNNING", "RUNNING": "SLEEPING", "SLEEPING": "ALL"}.get(state_filter, "ALL")
            processes = get_processes(sort_key, reverse, query.lower(), state_filter)
            page = selected = 0
            notice = f"Process state filter: {state_filter}"
        elif key in (curses.KEY_DOWN, ord("j")) and active_view == "PROCESSES":
            selected += 1
            if selected >= max(1, height - 14):
                selected = 0
                page += 1
                if page * max(1, height - 14) >= len(processes): page = 0
        elif key in (curses.KEY_UP, ord("k")) and active_view == "PROCESSES":
            selected = max(0, selected - 1)
        elif key in (ord("n"), ord("N")) and active_view == "PROCESSES":
            page += 1; selected = 0
            if page * max(1, height - 14) >= len(processes): page = 0
        elif key in (ord("p"), ord("P")) and active_view == "PROCESSES":
            page = max(0, page - 1); selected = 0
        elif key == ord("?"):
            notice = "Keys: 1 overview, 2 processes, 3 network, 4 storage, 5 system, space pause, r refresh, / search, s sort, v state filter, q quit."

def main():
    try:
        curses.wrapper(app)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
