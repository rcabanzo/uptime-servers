"""Create the initial password hash interactively, without plaintext storage."""
import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets

data = Path(os.environ.get('DATA_DIR', '/data'))
data.mkdir(parents=True, exist_ok=True)
target = data / 'auth.json'
if target.exists():
    raise SystemExit('Ya existe auth.json. No se sobrescribe.')
username = input('Usuario [admin]: ').strip() or 'admin'
if len(username) > 64:
    raise SystemExit('Usuario demasiado largo.')
password = getpass.getpass('Contraseña nueva (mínimo 16 caracteres): ')
if len(password) < 16 or len(password) > 1024:
    raise SystemExit('La contraseña debe tener entre 16 y 1024 caracteres.')
if password != getpass.getpass('Repite la contraseña: '):
    raise SystemExit('Las contraseñas no coinciden.')
salt = secrets.token_bytes(32)
record = dict(username=username, salt=salt.hex(), iterations=600000,
              hash=hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600000).hex())
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as output:
    json.dump(record, output)
print('Usuario creado. La contraseña no se guardó en texto plano.')
