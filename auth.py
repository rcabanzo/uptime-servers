"""Password login, persistent revocable sessions and login throttling."""
from contextlib import contextmanager
import hashlib
import hmac
import json
from http.cookies import SimpleCookie,CookieError
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time

DATA=Path(os.getenv('DATA_DIR',str(Path(__file__).parent/'data')))
COOKIE='__Host-serverpanel'
LIFETIME=24*3600
HASH_SLOTS=threading.BoundedSemaphore(2)
LOGIN_LOCK=threading.Lock()


@contextmanager
def database():
    DATA.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(DATA/'auth.sqlite',timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, username TEXT, csrf TEXT, expires REAL)')
    conn.execute('CREATE TABLE IF NOT EXISTS attempts (ip TEXT, time REAL)')
    conn.execute('CREATE INDEX IF NOT EXISTS attempts_ip_time ON attempts(ip,time)')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def cookie_token(header):
    try:
        jar=SimpleCookie()
        jar.load(header or '')
        value=jar[COOKIE].value
        return value if len(value)==43 else ''
    except (KeyError,ValueError,CookieError):
        return ''


def session(header):
    token=cookie_token(header)
    if not token:
        return None
    with database() as conn:
        row=conn.execute('SELECT username,csrf,expires FROM sessions WHERE token=? AND expires>?',(digest(token),time.time())).fetchone()
    return dict(username=row[0],csrf=row[1],expires=row[2]) if row else None


def login(username,password,ip):
    if not isinstance(username,str) or not isinstance(password,str) or len(username)>64 or len(password)>1024:
        return None,401
    now=time.time()
    # Record attempts before hashing: concurrent attempts cannot bypass the limit.
    with LOGIN_LOCK, database() as conn:
        conn.execute('DELETE FROM attempts WHERE time<?',(now-900,))
        count=conn.execute('SELECT COUNT(*) FROM attempts WHERE ip=?',(ip,)).fetchone()[0]
        global_count=conn.execute('SELECT COUNT(*) FROM attempts WHERE time>?',(now-60,)).fetchone()[0]
        if count>=5 or global_count>=60:
            return None,429
        conn.execute('INSERT INTO attempts VALUES (?,?)',(ip,now))
    if not HASH_SLOTS.acquire(blocking=False):
        return None,429
    try:
        record=json.loads((DATA/'auth.json').read_text())
        actual=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(record['salt']),record['iterations']).hex()
        valid=hmac.compare_digest(actual,record['hash']) & hmac.compare_digest(username.encode(),record['username'].encode())
    except Exception:
        return None,503
    finally:
        HASH_SLOTS.release()
    if not valid:
        return None,401
    token=secrets.token_urlsafe(32)
    csrf=secrets.token_urlsafe(32)
    with LOGIN_LOCK, database() as conn:
        conn.execute('DELETE FROM attempts WHERE ip=?',(ip,))
        conn.execute('DELETE FROM sessions WHERE expires<=?',(now,))
        conn.execute('INSERT INTO sessions VALUES (?,?,?,?)',(digest(token),username,csrf,now+LIFETIME))
        # Keep bounded even after many successful logins.
        conn.execute('DELETE FROM sessions WHERE token NOT IN (SELECT token FROM sessions ORDER BY expires DESC LIMIT 100)')
    return dict(token=token,csrf=csrf,username=username),200


def logout(header):
    token=cookie_token(header)
    if token:
        with database() as conn:
            conn.execute('DELETE FROM sessions WHERE token=?',(digest(token),))


def set_cookie(token='',clear=False,max_age=None):
    duration=0 if clear else LIFETIME if max_age is None else max(0,min(LIFETIME,int(max_age)))
    return f'{COOKIE}={token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age={duration}'
