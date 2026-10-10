# ServerPanel

Panel de monitorización WHM/cPanel con servidores en filas desplegables, CPU, RAM, disco, carga, disponibilidad e historial CSV. Comprobaciones cada 60 segundos, historial de 30 días y sesiones de 24 horas.

Diseño oscuro adaptable: filas compactas en escritorio, tarjetas con métricas etiquetadas en móvil, gráficas SVG de carga y latencia TCP, barras de recursos e historial de disponibilidad. Las gráficas conservan los intervalos sin muestras; no generan datos históricos de CPU/RAM inexistentes.

## Configuración

Copiar `.env.example` a `.env`, indicar el origen HTTPS del panel y crear `servers.json` con `[]`. `servers.example.json` documenta la configuración opcional mediante variables de entorno. No guardar credenciales en Git.

El servicio Docker publica exclusivamente `127.0.0.1:8787`. Debe instalarse detrás de un proxy HTTPS que sobrescriba `X-Real-IP` con la IP real del cliente. El firewall debe permitir únicamente los puertos necesarios; nunca publicar directamente 8787 o 8790.

Crear el usuario inicial con el asistente interactivo y arrancar el servicio:

```sh
cp .env.example .env
# Editar ALLOWED_ORIGIN en .env con el dominio HTTPS real.
printf '[]\n' > servers.json
docker compose build
docker compose run --rm panel python init_auth.py
docker compose up -d
```

El asistente guarda únicamente un hash PBKDF2-SHA256 con sal aleatoria y 600000 iteraciones en `/data/auth.json`, dentro del volumen persistente. No hay contraseña predeterminada y no se sobrescriben cuentas existentes.

## Recolector por SSH

Copiar los archivos de `scripts/` al servidor cPanel. Como root:

```sh
bash install-serverpanel-collector.sh
bash configure-serverpanel-apache.sh USUARIO_CPANEL DOMINIO_HTTPS IP_DEL_MONITOR
```

La configuración Apache requiere un dominio con certificado válido. Se detiene si encuentra NGINX o LiteSpeed. El recolector escucha en loopback y la ruta HTTPS se restringe a la IP del monitor. Registrar en el panel la URL `https://DOMINIO_HTTPS/serverpanel-metrics` y el token de `/etc/serverpanel-collector/token.env`.

WHM aporta carga; el recolector aporta CPU, RAM, disco y tiempo encendido. Las conexiones HTTPS validan certificados. Las credenciales se guardan en el volumen con permisos restringidos; root puede leerlas.

## Validación

```sh
python -m unittest test_auth test_monitor
```

El login usa hashes con sal, limitación de intentos, cookies Secure/HttpOnly/SameSite y sesiones revocables. Las modificaciones requieren sesión, origen autorizado y CSRF. Mantener copias de seguridad externas del volumen y configuración.
