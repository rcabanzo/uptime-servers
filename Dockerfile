FROM python:3.13-slim
WORKDIR /app
COPY server.py auth.py init_auth.py index.html app.js style.css login.html login.js login.css ./
RUN groupadd --gid 10001 panel && useradd --uid 10001 --gid panel --no-create-home panel && mkdir /data && chown panel:panel /data
USER 10001:10001
ENV BIND=0.0.0.0 PORT=8787 DATA_DIR=/data SERVERS_CONFIG=/config/servers.json PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8787
CMD ["python", "server.py"]
