#!/usr/bin/env bash
set -euo pipefail
[[ ${EUID} -eq 0 ]] || { echo 'Ejecuta como root.' >&2; exit 1; }
command -v systemctl >/dev/null || { echo 'Se necesita systemd.' >&2; exit 1; }
PYTHON=''
for candidate in python3 python3.13 python3.12 python3.11 python3.10 python3.9 python3.8; do
    if command -v "$candidate" >/dev/null && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3,8))'; then
        PYTHON=$(command -v "$candidate"); break
    fi
done
[[ -n "$PYTHON" ]] || { echo 'Instala Python 3.8 o posterior y vuelve a ejecutar.' >&2; exit 1; }
if ! getent passwd serverpanelmon >/dev/null; then
    NOLOGIN=$(command -v nologin || printf '/sbin/nologin')
    useradd --system --user-group --no-create-home --shell "$NOLOGIN" serverpanelmon
else
    [[ $(id -u serverpanelmon) -ne 0 ]] || { echo 'La cuenta serverpanelmon no puede ser root.' >&2; exit 1; }
fi
install -d -m 755 -o root -g root /opt/serverpanel-collector
if [[ -f /opt/serverpanel-collector/collector.py ]]; then
    cp -p /opt/serverpanel-collector/collector.py "/opt/serverpanel-collector/collector.py.backup-$(date +%Y%m%dT%H%M%S)"
fi
cat > /opt/serverpanel-collector/collector.py <<'COLLECTOR_PY'
"""Read-only Linux metrics collector. Place behind an HTTPS reverse proxy.
Never expose its HTTP port publicly. Token provided as COLLECTOR_TOKEN.
"""
import hmac
import http.server
import json
import os
from pathlib import Path
import shutil
import threading
import time

METRICS = {}
LOCK = threading.Lock()


def cpu_ticks():
    ticks = list(map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
    return sum(ticks), ticks[3]+ticks[4]


def collect():
    previous = cpu_ticks()
    while True:
        time.sleep(1)
        current = cpu_ticks()
        total = current[0]-previous[0]
        cpu = 100*(1-(current[1]-previous[1])/total) if total else 0
        previous = current
        mem = {line.split(':')[0]: int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()}
        mount = os.getenv('DISK_MOUNT','/')
        disk = shutil.disk_usage(mount)
        metrics = dict(cpu=round(cpu,1), ram=round(100*(1-mem['MemAvailable']/mem['MemTotal']),1), disk=round(100*disk.used/disk.total,1), diskUsedGb=round(disk.used/1e9,1), diskTotalGb=round(disk.total/1e9,1), load=os.getloadavg()[0], bootSeconds=float(Path('/proc/uptime').read_text().split()[0]), mount=mount)
        with LOCK:
            METRICS.update(metrics)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        expected = 'Bearer '+os.environ['COLLECTOR_TOKEN']
        if not hmac.compare_digest(self.headers.get('Authorization',''), expected):
            self.send_error(401)
            return
        if self.path != '/metrics':
            self.send_error(404)
            return
        with LOCK:
            raw = json.dumps(METRICS).encode()
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self,*args):
        pass


if __name__ == '__main__':
    if len(os.getenv('COLLECTOR_TOKEN','')) < 32:
        raise SystemExit('COLLECTOR_TOKEN must contain at least 32 characters')
    threading.Thread(target=collect,daemon=True).start()
    http.server.ThreadingHTTPServer(('127.0.0.1',int(os.getenv('COLLECTOR_PORT','8790'))),Handler).serve_forever()

COLLECTOR_PY
chown root:root /opt/serverpanel-collector/collector.py
chmod 644 /opt/serverpanel-collector/collector.py
if [[ ! -f /etc/serverpanel-collector.env ]]; then
    "$PYTHON" - <<'PY'
import os,secrets
path='/etc/serverpanel-collector.env'
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f:
    f.write('COLLECTOR_TOKEN='+secrets.token_urlsafe(48)+'\nCOLLECTOR_PORT=8790\nDISK_MOUNT=/\n')
PY
fi
chown root:root /etc/serverpanel-collector.env
chmod 600 /etc/serverpanel-collector.env
cat > /etc/systemd/system/serverpanel-collector.service <<UNIT
[Unit]
Description=ServerPanel read-only Linux metrics collector
After=network.target
[Service]
Type=simple
User=serverpanelmon
Group=$(id -gn serverpanelmon)
EnvironmentFile=/etc/serverpanel-collector.env
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=$PYTHON /opt/serverpanel-collector/collector.py
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
CapabilityBoundingSet=
RestrictAddressFamilies=AF_INET AF_UNIX
RestrictRealtime=true
UMask=0077
MemoryMax=128M
TasksMax=64
[Install]
WantedBy=multi-user.target
UNIT
chmod 644 /etc/systemd/system/serverpanel-collector.service
systemctl daemon-reload
systemctl enable serverpanel-collector
systemctl restart serverpanel-collector
"$PYTHON" - <<'PY'
import json,time,urllib.request
token=None
for line in open('/etc/serverpanel-collector.env'):
    if line.startswith('COLLECTOR_TOKEN='): token=line.split('=',1)[1].strip()
if not token: raise SystemExit('Falta COLLECTOR_TOKEN')
request=urllib.request.Request('http://127.0.0.1:8790/metrics',headers={'Authorization':'Bearer '+token})
for attempt in range(15):
    try:
        with urllib.request.urlopen(request,timeout=2) as response: metrics=json.load(response)
        if all(key in metrics for key in ('cpu','ram','disk','load')):
            print('Recolector instalado. Prueba local correcta:',json.dumps(metrics)); break
    except Exception: pass
    time.sleep(1)
else: raise SystemExit('No se pudo verificar. Ejecuta: journalctl -u serverpanel-collector -n 30 --no-pager')
PY
printf '\nToken guardado en /etc/serverpanel-collector.env (solo root).\n'
printf 'Recolector en 127.0.0.1:8790; no abras este puerto en el firewall.\n'
printf 'Siguiente paso: configurar la ruta HTTPS con configure-serverpanel-apache.sh.\n'
