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
