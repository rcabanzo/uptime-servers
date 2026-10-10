#!/usr/bin/env bash
set -euo pipefail
[[ ${EUID} -eq 0 ]] || { echo 'Ejecuta como root.' >&2; exit 1; }
[[ $# -eq 3 ]] || { echo 'Uso: bash configure-serverpanel-apache.sh USUARIO_CPANEL DOMINIO_HTTPS IP_MONITOR'; exit 1; }
CPANEL_USER=$1
DOMAIN=$2
MONITOR_IP=$3
python3 -c "import ipaddress,sys; ipaddress.ip_address(sys.argv[1])" "$MONITOR_IP"
[[ "$CPANEL_USER" =~ ^[a-zA-Z0-9_][a-zA-Z0-9_-]{0,63}$ ]] || { echo 'Usuario invalido.'; exit 1; }
[[ "$DOMAIN" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]] || { echo 'Dominio invalido.'; exit 1; }
[[ -f "/var/cpanel/users/$CPANEL_USER" && -f "/var/cpanel/userdata/$CPANEL_USER/${DOMAIN}_SSL" ]] || { echo 'No existe ese dominio SSL para esa cuenta cPanel. Usa un dominio con certificado valido.'; exit 1; }
if pgrep -x nginx >/dev/null || pgrep -x litespeed >/dev/null || pgrep -x lshttpd >/dev/null; then
    echo 'Hay NGINX o LiteSpeed activo. Este script es para Apache directo; solicita la configuracion adecuada antes de continuar.'
    exit 1
fi
APACHECTL=/usr/local/apache/bin/apachectl
[[ -x "$APACHECTL" ]] || APACHECTL=$(command -v apachectl)
MODULES=$("$APACHECTL" -M 2>&1)
[[ "$MODULES" == *proxy_module* && "$MODULES" == *proxy_http_module* ]] || { echo 'Activa mod_proxy y mod_proxy_http en EasyApache 4 primero.'; exit 1; }
systemctl is-active --quiet serverpanel-collector || { echo 'Instala y activa primero el recolector.'; exit 1; }
curl --fail --silent --show-error --max-time 10 --output /dev/null "https://$DOMAIN/" || { echo 'No se pudo comprobar HTTPS. Revisa DNS, certificado y respuesta de ese dominio.'; exit 1; }
INCLUDE_DIR="/etc/apache2/conf.d/userdata/ssl/2_4/$CPANEL_USER/$DOMAIN"
CONF="$INCLUDE_DIR/serverpanel-collector.conf"
[[ ! -e "$CONF" ]] || { echo 'Ya existe el include; no se sobrescribe. Revisa su configuracion.'; exit 1; }
install -d -m 755 "$INCLUDE_DIR"
cat > "$CONF" <<APACHE
ProxyPass "/serverpanel-metrics" "http://127.0.0.1:8790/metrics" connectiontimeout=3 timeout=5
ProxyPassReverse "/serverpanel-metrics" "http://127.0.0.1:8790/metrics"
<Location "/serverpanel-metrics">
    Require ip $MONITOR_IP
</Location>
APACHE
chmod 644 "$CONF"
rollback() {
    echo 'No se aplico la configuracion. Se retira el nuevo include y se restaura la configuracion previa.' >&2
    rm -f -- "$CONF"
    /usr/local/cpanel/scripts/rebuildhttpdconf || true
}
if ! /usr/local/cpanel/scripts/rebuildhttpdconf || ! "$APACHECTL" -t; then
    rollback
    exit 1
fi
if ! /usr/local/cpanel/scripts/restartsrv_httpd; then
    rollback
    /usr/local/cpanel/scripts/restartsrv_httpd || true
    exit 1
fi
printf '\nURL del recolector: https://%s/serverpanel-metrics\n' "$DOMAIN"
printf 'Token: el valor COLLECTOR_TOKEN del archivo /etc/serverpanel-collector.env.\n'
printf 'La ruta admite solo la IP $MONITOR_IP. Verifica la lectura desde el panel.\n'
