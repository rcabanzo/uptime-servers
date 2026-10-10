"""Read-only server monitor. Python 3.12+, standard library only."""
import concurrent.futures
from contextlib import contextmanager
import http.server
import json
import math
import os
from pathlib import Path
import re
import socket
import sqlite3
import ssl
import threading
import time
import urllib.request
import auth

ROOT = Path(__file__).resolve().parent
DATA = Path(os.getenv('DATA_DIR', str(ROOT / 'data')))
CONFIG = Path(os.getenv('SERVERS_CONFIG', str(ROOT / 'servers.json')))
INTERVAL = 60
STATE = {'servers': [], 'demo': False}
LOCK = threading.Lock()
CONFIG_LOCK = threading.Lock()
WAKE = threading.Event()
SECRETS = {}


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


@contextmanager
def connect_db():
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATA / 'history.sqlite', timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('CREATE TABLE IF NOT EXISTS checks (server TEXT, time REAL, ok INTEGER, latency REAL, load REAL)')
    conn.execute('CREATE INDEX IF NOT EXISTS checks_server_time ON checks(server, time)')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward API credentials across redirects.
        return None


def fetch_json(url, headers=None):
    if not url.startswith('https://'):
        raise ValueError('HTTPS required')
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(urllib.request.Request(url, headers=headers or {}), timeout=8) as response:
        raw = response.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError('Response too large')
        return json.loads(raw)


def tcp_check(host, port):
    start = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=3):
            return True, round((time.monotonic() - start) * 1000, 1)
    except OSError:
        return False, None


def check_server(cfg):
    host = cfg['host']
    ports = cfg.get('ports', {'HTTPS': 443, 'WHM': 2087, 'cPanel': 2083, 'SSH': 22})
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = dict(zip(ports, pool.map(lambda pair: tcp_check(host, int(pair[1])), ports.items())))
    primary = cfg.get('primary', 'WHM')
    ok, latency = results.get(primary, (False, None))
    result = dict(id=cfg['id'], name=cfg.get('name', host), status='healthy' if ok else 'down', disk=None, load=None, cpu=None, ram=None, latency=latency, checkedAt=time.time(), diskUsedGb=None, diskTotalGb=None, bootSeconds=None, services={k: v[0] for k, v in results.items()}, whmUrl=f'https://{host}:{ports.get("WHM",2087)}', cpanelUrl=f'https://{host}:{ports.get("cPanel",2083)}', error='')
    errors = []
    if cfg.get('metrics_url'):
        token = os.getenv(cfg.get('metrics_token_env', ''), '') or SECRETS.get(cfg['id'],{}).get('metricsToken','')
        try:
            if not token:
                raise ValueError('Missing collector token')
            metrics = fetch_json(cfg['metrics_url'], {'Authorization': 'Bearer ' + token})
            for key in ('disk', 'load', 'cpu', 'ram', 'diskUsedGb', 'diskTotalGb', 'bootSeconds'):
                result[key] = number(metrics.get(key))
            result['mount'] = str(metrics.get('mount', '/'))[:100]
        except Exception:
            errors.append('Recolector no disponible: revisar conexión o credenciales.')
    if cfg.get('whm_token_env'):
        token = os.getenv(cfg['whm_token_env'], '') or SECRETS.get(cfg['id'],{}).get('whmToken','')
        try:
            if not token:
                raise ValueError('Missing WHM token')
            payload = fetch_json(result['whmUrl'] + '/json-api/systemloadavg?api.version=1', {'Authorization': f'whm {cfg.get("whm_user","root")}:{token}'})
            if payload.get('metadata', {}).get('result') != 1:
                raise ValueError('WHM rejected the request')
            result['load'] = number(payload.get('data', {}).get('one'))
        except Exception:
            errors.append('API WHM no disponible: revisar certificado, permisos o token.')
    if not ok:
        errors.insert(0, f'Servicio principal {primary} sin conexión.')
    elif (any(not value[0] for value in results.values()) or errors or (result['disk'] or 0) >= 90 or (result['ram'] or 0) >= 90 or (result['load'] or 0) >= float(cfg.get('load_warning', 6))):
        result['status'] = 'warning'
    result['error'] = ' '.join(errors)
    result['_ok'] = ok
    return result


def validate_config(config):
    seen = set()
    if not isinstance(config, list) or len(config) > 100:
        raise ValueError('Expected a list of up to 100 servers')
    for cfg in config:
        identifier = cfg.get('id', '')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', identifier) or identifier in seen:
            raise ValueError('Invalid or duplicate server ID')
        seen.add(identifier)
        host = cfg.get('host', '')
        if not re.fullmatch(r'[a-zA-Z0-9.-]{1,253}', host):
            raise ValueError('Invalid hostname or IPv4 address')
        ports = cfg.get('ports', {'HTTPS': 443, 'WHM': 2087, 'cPanel': 2083, 'SSH': 22})
        if not ports or len(ports) > 8 or cfg.get('primary', 'WHM') not in ports:
            raise ValueError('Invalid primary service or ports')
        if any(not isinstance(p, int) or not 1 <= p <= 65535 for p in ports.values()):
            raise ValueError('Invalid port')
    return config


def demo_data():
    now = time.time()
    servers = []
    for i, (name, disk, load, cpu, ram, latency) in enumerate([
        ('hosting-01', 62, 1.24, 24, 58, 32), ('hosting-02', 38, .62, 12, 41, 28),
        ('hosting-03', 91, 6.82, 87, 78, 120), ('backup-01', 27, .18, 8, 36, 24)]):
        history = [dict(time=now-(59-j)*60, ok=True, latency=latency, load=round(load*(1+.15*math.sin(j*.7)), 2)) for j in range(60)]
        servers.append(dict(id=name, name=name+'.example.com', status='warning' if i==2 else 'healthy', disk=disk, load=load, cpu=cpu, ram=ram, latency=latency, checkedAt=now, uptime=100, diskUsedGb=disk*10, diskTotalGb=1000, bootSeconds=86400*27, history=history, services={'HTTPS': True, 'WHM': True, 'cPanel': True, 'SSH': True}, error=''))
    return {'servers': servers, 'demo': True}


def cycle():
    if os.getenv('DEMO', '0') == '1' and not (DATA / 'servers.json').exists():
        state = demo_data()
    else:
        with CONFIG_LOCK:
            configs = read_config()
            if (DATA / 'secrets.json').exists():
                SECRETS.clear()
                SECRETS.update(json.loads((DATA / 'secrets.json').read_text(encoding='utf-8')))
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            servers = list(pool.map(check_server, configs))
        with connect_db() as conn:
            for server in servers:
                conn.execute('INSERT INTO checks VALUES (?, ?, ?, ?, ?)', (server['id'], server['checkedAt'], int(server.pop('_ok')), server['latency'], server['load']))
                rows = conn.execute('SELECT time,ok,latency,load FROM checks WHERE server=? AND time>=? ORDER BY time', (server['id'], time.time()-86400)).fetchall()
                server['history'] = [dict(time=t, ok=bool(ok), latency=lat, load=load) for t,ok,lat,load in rows]
                server['uptime'] = 100*sum(r[1] for r in rows)/len(rows) if rows else None
            conn.execute('DELETE FROM checks WHERE time<?', (time.time()-30*86400,))
        state = {'servers': servers, 'demo': False}
    with LOCK:
        STATE.clear()
        STATE.update(state)
        STATE['lastCycleAt'] = time.time()


def monitor():
    while True:
        start = time.monotonic()
        try:
            cycle()
        except Exception as exc:
            # Do not log config or credential-bearing request strings.
            print('Monitoring cycle failed:', type(exc).__name__, flush=True)
            with LOCK:
                STATE['monitorError'] = 'No se completó el ciclo de monitorización. Revisar configuración.'
        WAKE.wait(max(1, INTERVAL-(time.monotonic()-start)))
        WAKE.clear()


def read_config():
    path = DATA / 'servers.json' if (DATA / 'servers.json').exists() else CONFIG
    return validate_config(json.loads(path.read_text(encoding='utf-8')))


def save_json(path, value):
    temp = path.with_suffix('.tmp')
    with open(temp,'w',encoding='utf-8') as handle:
        os.chmod(temp,0o600)
        json.dump(value,handle,ensure_ascii=False)
    os.replace(temp,path)


def add_server(payload):
    from urllib.parse import urlsplit
    host = str(payload.get('host','')).strip().lower()
    identifier = re.sub(r'[^a-z0-9_-]','-',host)[:60]
    user = str(payload.get('whm_user','root'))
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',user):
        raise ValueError('Usuario WHM inválido')
    whm_port = int(payload.get('whm_port',2087))
    cfg = dict(id=identifier,host=host,name=str(payload.get('name',host))[:100],whm_user=user,primary='WHM',ports={'HTTPS':443,'WHM':whm_port,'cPanel':2083,'SSH':22})
    credentials = {}
    for field in ('whmToken','metricsToken'):
        value = str(payload.get(field,''))
        if len(value)>1024 or any(ord(c)<32 for c in value):
            raise ValueError('Token inválido')
        if value:
            credentials[field]=value
    if credentials.get('whmToken'):
        cfg['whm_token_env']='WHM_'+identifier.upper().replace('-','_')+'_TOKEN'
    metrics_url = str(payload.get('metrics_url','')).strip()
    if metrics_url:
        url = urlsplit(metrics_url)
        if url.scheme!='https' or not url.hostname or url.username or url.password or len(metrics_url)>1000:
            raise ValueError('El recolector requiere una URL HTTPS válida')
        if not credentials.get('metricsToken'):
            raise ValueError('Falta el token del recolector')
        cfg['metrics_url']=metrics_url
        cfg['metrics_token_env']='METRICS_'+identifier.upper().replace('-','_')+'_TOKEN'
    validate_config([cfg])
    with CONFIG_LOCK:
        configs=read_config()
        if any(c['id']==identifier for c in configs):
            raise ValueError('Este servidor ya está añadido')
        validate_config(configs+[cfg])
        DATA.mkdir(parents=True,exist_ok=True)
        secrets_path=DATA/'secrets.json'
        secrets=json.loads(secrets_path.read_text()) if secrets_path.exists() else {}
        secrets[identifier]=credentials
        save_json(secrets_path,secrets)
        save_json(DATA/'servers.json',configs+[cfg])
    WAKE.set()
    return identifier


class Handler(http.server.BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def json_response(self,status,value,cookie=None):
        raw=json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        if cookie:
            self.send_header('Set-Cookie',cookie)
        if status==429:
            self.send_header('Retry-After','900')
        self.end_headers()
        self.wfile.write(raw)

    def current_session(self):
        return auth.session(self.headers.get('Cookie',''))

    def redirect(self,path):
        self.send_response(303)
        self.send_header('Location',path)
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length','0')
        self.end_headers()

    def do_POST(self):
        origin=os.getenv('ALLOWED_ORIGIN','https://monitor.example.com')
        if self.headers.get('Origin')!=origin or self.headers.get('Content-Type','').split(';')[0]!='application/json':
            self.send_error(403)
            return
        if self.path not in ('/api/servers','/api/login','/api/logout'):
            self.send_error(404)
            return
        current=self.current_session() if self.path!='/api/login' else None
        if self.path!='/api/login':
            if not current:
                self.json_response(401,{'error':'Inicia sesión para continuar.'})
                return
            import hmac
            if not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),current['csrf']):
                self.json_response(403,{'error':'Solicitud no autorizada.'})
                return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=16384:
                self.send_error(413)
                return
            self.connection.settimeout(10)
            payload=json.loads(self.rfile.read(length))
            if not isinstance(payload,dict):
                raise ValueError('Datos inválidos')
            if self.path=='/api/login':
                ip=self.headers.get('X-Real-IP',self.client_address[0])[:100]
                result,status=auth.login(payload.get('username'),payload.get('password'),ip)
                if result:
                    self.json_response(200,{'ok':True},auth.set_cookie(result['token']))
                else:
                    message={401:'Usuario o contraseña incorrectos.',429:'Demasiados intentos. Espera 15 minutos e inténtalo de nuevo.',503:'Inicio de sesión temporalmente no disponible.'}[status]
                    self.json_response(status,{'error':message})
                return
            if self.path=='/api/logout':
                auth.logout(self.headers.get('Cookie',''))
                self.json_response(200,{'ok':True},auth.set_cookie(clear=True))
                return
            identifier=add_server(payload)
            raw=json.dumps({'ok':True,'id':identifier}).encode()
            status=201
        except (ValueError,TypeError,KeyError):
            raw=json.dumps({'error':'No se pudo guardar. Revisa hostname, puerto, tokens y posibles duplicados.'}).encode()
            status=400
        except Exception:
            raw=b'{"error":"No se pudo guardar la configuracion."}'
            status=500
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        public=('/login','/login.html','/login.js','/login.css','/healthz')
        current=self.current_session() if path not in public else None
        if path not in public and not current:
            if path.startswith('/api/'):
                self.json_response(401,{'error':'Inicia sesión para continuar.'})
            else:
                self.redirect('/login')
            return
        if path=='/api/session':
            self.json_response(200,{'username':current['username'],'csrf':current['csrf']})
            return
        if path == '/api/status':
            with LOCK:
                raw = json.dumps(STATE, allow_nan=False).encode()
            mime = 'application/json; charset=utf-8'
        elif path == '/healthz':
            with LOCK:
                healthy = not STATE.get('monitorError') and time.time()-STATE.get('lastCycleAt',0)<180
            if not healthy:
                self.send_error(503)
                return
            raw, mime = b'ok', 'text/plain'
        elif path in ('/', '/index.html', '/app.js', '/style.css','/login','/login.html','/login.js','/login.css'):
            name = 'index.html' if path == '/' else 'login.html' if path=='/login' else path[1:]
            raw = (ROOT / name).read_bytes()
            mime = {'html': 'text/html; charset=utf-8', 'js': 'text/javascript; charset=utf-8', 'css': 'text/css; charset=utf-8'}[name.rsplit('.',1)[1]]
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if path=='/api/status' and current:
            self.send_header('Set-Cookie',auth.set_cookie(auth.cookie_token(self.headers.get('Cookie','')),max_age=current['expires']-time.time()))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt, *args):
        pass


class BoundedHTTPServer(http.server.ThreadingHTTPServer):
    slots=threading.BoundedSemaphore(32)

    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request,address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self,request,address):
        try:
            super().process_request_thread(request,address)
        finally:
            self.slots.release()


if __name__ == '__main__':
    if os.getenv('DEMO', '0') != '1':
        read_config()
    threading.Thread(target=monitor, daemon=True).start()
    bind = os.getenv('BIND', '127.0.0.1')
    print(f'ServerPanel listening on {bind}:{os.getenv("PORT", "8787")}', flush=True)
    BoundedHTTPServer((bind, int(os.getenv('PORT','8787'))), Handler).serve_forever()
