"""NEXUS SYSWATCH local Linux telemetry API."""
import asyncio
import os
import platform
import socket
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import psutil
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

DB = Path(os.getenv('NEXUS_DB', str(Path.home() / '.local/share/nexus-syswatch/metrics.sqlite3')))
DB.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(f'sqlite:///{DB}', connect_args={'check_same_thread': False})
with engine.begin() as conn:
    conn.execute(text('CREATE TABLE IF NOT EXISTS samples (ts REAL PRIMARY KEY, cpu REAL, memory REAL, swap REAL, disk REAL, download REAL, upload REAL)'))
    conn.execute(text('CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, metric TEXT NOT NULL, threshold REAL NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, last_trigger REAL DEFAULT 0)'))
    conn.execute(text('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, message TEXT)'))
    conn.execute(text('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)'))
latest = {}
previous_net = None
previous_time = None
subscribers = set()


def sample():
    global previous_net, previous_time, latest
    now = time.time()
    net = psutil.net_io_counters()
    elapsed = now - previous_time if previous_time else 0
    down = max(0, (net.bytes_recv - previous_net.bytes_recv) / elapsed) if previous_net and elapsed > 0 else 0
    up = max(0, (net.bytes_sent - previous_net.bytes_sent) / elapsed) if previous_net and elapsed > 0 else 0
    previous_net, previous_time = net, now
    latest = {'ts': now, 'cpu': psutil.cpu_percent(interval=None), 'memory': psutil.virtual_memory().percent,
              'swap': psutil.swap_memory().percent, 'disk': psutil.disk_usage('/').percent,
              'download': down, 'upload': up, 'uptime': int(now - psutil.boot_time()),
              'ram_total': psutil.virtual_memory().total, 'ram_available': psutil.virtual_memory().available,
              'per_core': psutil.cpu_percent(interval=None, percpu=True)}
    with engine.begin() as conn:
        conn.execute(text('INSERT OR REPLACE INTO samples VALUES (:ts,:cpu,:memory,:swap,:disk,:download,:upload)'), {k: latest[k] for k in ('ts','cpu','memory','swap','disk','download','upload')})
        for row in conn.execute(text('SELECT id,metric,threshold,last_trigger FROM alerts WHERE enabled=1')).mappings():
            if latest.get(row['metric'], 0) >= row['threshold'] and now - row['last_trigger'] >= 300:
                message = f"{row['metric'].upper()} exceeded {row['threshold']}%"
                conn.execute(text('INSERT INTO events(ts,message) VALUES (:ts,:msg)'), {'ts':now,'msg':message})
                conn.execute(text('UPDATE alerts SET last_trigger=:ts WHERE id=:id'), {'ts':now,'id':row['id']})
        conn.execute(text('DELETE FROM samples WHERE ts < :cutoff'), {'cutoff': now - 86400 * 7})
    return latest


async def collector():
    psutil.cpu_percent(interval=None)
    while True:
        await asyncio.to_thread(sample)
        await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(collector())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title='NEXUS // SYSWATCH', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173','http://127.0.0.1:5173'], allow_methods=['GET','POST','PATCH','DELETE'], allow_headers=['*'])


@app.get('/api/health')
def health(): return {'status': 'ok', 'version': '0.1.0'}


@app.get('/api/system')
def system():
    return {'hostname': socket.gethostname(), 'os': platform.platform(), 'kernel': platform.release(),
            'architecture': platform.machine(), 'python': platform.python_version(),
            'cores': psutil.cpu_count(), 'boot_time': psutil.boot_time(), 'ram_total': psutil.virtual_memory().total}


@app.get('/api/metrics')
def metrics(): return latest or sample()


@app.get('/api/metrics/history')
def history(range: str = '5m'):
    ranges = {'1m':60,'5m':300,'15m':900,'1h':3600,'24h':86400}
    if range not in ranges: raise HTTPException(422, 'Unsupported range')
    with engine.connect() as conn:
        rows = conn.execute(text('SELECT * FROM samples WHERE ts >= :since ORDER BY ts DESC LIMIT 1500'), {'since': time.time()-ranges[range]}).mappings().all()
    return list(reversed([dict(r) for r in rows]))


@app.get('/api/processes')
def processes(search: str = '', sort: str = 'cpu', limit: int = 100):
    if sort not in ('cpu','memory','pid','name'): raise HTTPException(422, 'Invalid sort')
    out = []
    for proc in psutil.process_iter(['pid','name','username','cpu_percent','memory_percent','status','create_time'], ad_value=None):
        try:
            p = proc.info
            if search.lower() not in str(p['name']).lower() and search not in str(p['pid']): continue
            out.append({'pid':p['pid'], 'name':p['name'], 'username':p['username'], 'cpu':p['cpu_percent'] or 0,
                        'memory':round(p['memory_percent'] or 0,2), 'status':p['status'], 'started':p['create_time']})
        except (psutil.NoSuchProcess, psutil.AccessDenied): continue
    return sorted(out, key=lambda p:p[sort] or 0, reverse=sort not in ('name','pid'))[:max(1,min(limit,500))]


@app.get('/api/processes/{pid}')
def process_detail(pid: int):
    try:
        p = psutil.Process(pid)
        return {'pid':p.pid,'name':p.name(),'status':p.status(),'memory':p.memory_info().rss,'started':p.create_time()}
    except (psutil.NoSuchProcess, psutil.AccessDenied): raise HTTPException(404, 'Process unavailable')


@app.get('/api/network/interfaces')
def interfaces(): return list(psutil.net_if_addrs().keys())


@app.get('/api/storage')
def storage():
    out=[]
    for p in psutil.disk_partitions(all=False):
        try:
            d=psutil.disk_usage(p.mountpoint)
            out.append({'device':p.device,'mount':p.mountpoint,'total':d.total,'used':d.used,'free':d.free,'percent':d.percent})
        except (OSError, PermissionError): pass
    return out


class AlertInput(BaseModel):
    metric: str
    threshold: float = Field(ge=0,le=100)
    enabled: bool = True


@app.get('/api/alerts')
def alerts():
    with engine.connect() as conn:
        return {'rules':[dict(r) for r in conn.execute(text('SELECT * FROM alerts ORDER BY id DESC')).mappings()],
                'events':[dict(r) for r in conn.execute(text('SELECT * FROM events ORDER BY id DESC LIMIT 30')).mappings()]}


@app.post('/api/alerts',status_code=201)
def create_alert(alert: AlertInput):
    if alert.metric not in ('cpu','memory','swap','disk'): raise HTTPException(422,'Unsupported metric')
    with engine.begin() as conn:
        result=conn.execute(text('INSERT INTO alerts(metric,threshold,enabled) VALUES (:m,:t,:e)'),{'m':alert.metric,'t':alert.threshold,'e':int(alert.enabled)})
        return {'id':result.lastrowid,**alert.model_dump()}


@app.delete('/api/alerts/{id}')
def delete_alert(id: int):
    with engine.begin() as conn: conn.execute(text('DELETE FROM alerts WHERE id=:id'),{'id':id})
    return {'deleted':True}


@app.patch('/api/alerts/{id}')
def patch_alert(id: int, alert: AlertInput):
    if alert.metric not in ('cpu','memory','swap','disk'): raise HTTPException(422,'Unsupported metric')
    with engine.begin() as conn:
        result=conn.execute(text('UPDATE alerts SET metric=:m,threshold=:t,enabled=:e WHERE id=:id'),{'m':alert.metric,'t':alert.threshold,'e':int(alert.enabled),'id':id})
        if not result.rowcount: raise HTTPException(404,'Rule not found')
    return {'id':id,**alert.model_dump()}


@app.get('/api/settings')
def settings():
    with engine.connect() as conn: return {r['key']:r['value'] for r in conn.execute(text('SELECT * FROM settings')).mappings()}


@app.patch('/api/settings')
def save_settings(values: dict[str,str]):
    allowed={'density','animations','refresh'}
    for k,v in values.items():
        if k not in allowed or len(v)>30: raise HTTPException(422,'Invalid setting')
    with engine.begin() as conn:
        for k,v in values.items(): conn.execute(text('INSERT INTO settings VALUES (:k,:v) ON CONFLICT(key) DO UPDATE SET value=:v'),{'k':k,'v':v})
    return values


@app.websocket('/ws/metrics')
async def websocket_metrics(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            await ws.send_json(latest)
            await asyncio.sleep(2)
    except (WebSocketDisconnect, RuntimeError): pass
