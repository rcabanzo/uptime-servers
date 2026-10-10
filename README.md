# ServerPanel

Panel de monitorización WHM/cPanel con servidores en filas desplegables, CPU, RAM, disco, carga, disponibilidad e historial CSV. Comprobaciones cada 60 segundos, historial de 30 días y sesiones de 24 horas.

Consola oscura con identidad visual común en el panel, login y formulario de conexión. Resumen de infraestructura en la parte superior, filas compactas en escritorio y tarjetas con métricas etiquetadas en móvil, con navegación inferior táctil. Las alertas y la latencia media aparecen en un popup a la derecha que se puede cerrar y reabrir desde la campana. Sin fuentes, librerías o servicios externos en el navegador.

Cada servidor despliega gráficas SVG de carga y latencia TCP con selector de 2/24 horas, medias y picos; barras de CPU/RAM/disco y comprobaciones de disponibilidad. Las gráficas conservan los intervalos sin muestras y los huecos entre comprobaciones. No se generan históricos ficticios de CPU/RAM. Búsqueda por nombre o dirección, filtros, alertas y exportación CSV.

El diseño contempla navegación por teclado, foco visible, reducción de movimiento y pantallas de 320 px en adelante. La sesión continúa siendo de 24 horas; las comprobaciones del backend mantienen su intervalo de 60 segundos.

## Editar un servidor

Usar el botón del lápiz junto al nombre para cambiar nombre, hostname/IP, usuario y puerto WHM, tokens o URL del recolector. Guardar mantiene el identificador y su historial. Los tokens existentes no se envían al navegador: dejarlos vacíos conserva sus valores. Las opciones para retirar un token son explícitas; retirar el token del recolector también desconecta esa integración. Los cambios activan una nueva comprobación.

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
