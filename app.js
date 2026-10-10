/* Responsive monitoring and SVG charts. No external browser dependencies. */
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[char]));
const icons = {
  servers:'<rect x="3" y="3" width="18" height="7" rx="2"/><rect x="3" y="14" width="18" height="7" rx="2"/><path d="M7 6.5h.01M7 17.5h.01M11 6.5h6M11 17.5h6"/>',
  activity:'<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  bell:'<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
  settings:'<path d="M12 3v3m0 12v3M3 12h3m12 0h3M5.6 5.6l2.1 2.1m8.6 8.6 2.1 2.1M5.6 18.4l2.1-2.1m8.6-8.6 2.1-2.1"/><circle cx="12" cy="12" r="5"/>',
  logout:'<path d="M9 4H4v16h5m7-12 4 4-4 4M8 12h12"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  refresh:'<path d="M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 13 3M5 15a8 8 0 0 0 13 3"/>',
  search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  chevron:'<path d="m9 5 7 7-7 7"/>',close:'<path d="m6 6 12 12M6 18 18 6"/>',
  shield:'<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m8 12 3 3 5-6"/>',
  arrow:'<path d="M7 17 17 7M7 7h10v10"/>',download:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  edit:'<path d="m16 3 5 5L9 20l-6 1 1-6zM13 6l5 5"/>',
  check:'<path d="m5 12 4 4L19 6"/>',warning:'<path d="m12 3 10 18H2zM12 9v5m0 3h.01"/>',disk:'<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M3 13h18M16 16h.01M12 16h.01"/>'
};
const icon = name => `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.activity}</svg>`;
document.querySelectorAll('[data-icon]').forEach(el => { el.innerHTML = icon(el.dataset.icon); });
const num = value => Number.isFinite(value) ? value.toLocaleString('es-CO', { maximumFractionDigits:2 }) : '—';
const pct = value => Number.isFinite(value) ? `${value.toLocaleString('es-CO', { maximumFractionDigits:1 })}%` : '—';
const mean = values => values.length ? values.reduce((a,b) => a+b,0) / values.length : null;
const timeLabel = timestamp => new Date(timestamp * 1000).toLocaleTimeString('es-CO', { hour:'2-digit', minute:'2-digit' });
const statusName = status => ({ healthy:'Operativo', warning:'Atención', down:'Sin conexión' }[status] || 'Pendiente');
const safeURL = value => { try { const url = new URL(value); return url.protocol === 'https:' ? url.href : ''; } catch { return ''; } };
const serverHost = server => { try { return server.host || server.hostname || new URL(safeURL(server.whmUrl)).hostname; } catch { return ''; } };
let data = { servers:[], demo:false }, expanded = new Set(), view = 'servers', remaining = 60, busy = false, csrf = '', chartId = 0, firstLoad = true;
const ranges = new Map();
let editingId = null, dialogRequest = 0, alertSignature = null;
function bar(value, color='mint') {
  const width = Number.isFinite(value) ? Math.max(0,Math.min(100,value)) : 0;
  return `<span class="resource-bar"><span class="${value >= 90 ? 'amber' : color}" style="width:${width}%"></span></span>`;
}
function visibleHistory(server) {
  const history = server.history || [], hours = ranges.get(server.id) || 2, end = history.at(-1)?.time || Date.now()/1000;
  return history.filter(point => point.time >= end - hours*3600);
}
function graph(history, key='load', compact=false) {
  const samples = history.filter(s => Number.isFinite(s.time)), values = samples.map(s => s[key]).filter(Number.isFinite);
  if (!values.length) return `<div class="chart-empty ${compact ? 'compact' : ''}">${icon('activity')}<span>El historial aparecerá con las primeras muestras</span></div>`;
  const W=600, H=compact?100:180, left=compact?0:34, right=compact?600:590, top=compact?8:15, bottom=compact?98:148;
  const max=Math.max(1,...values)*1.15, start=samples[0].time, end=samples.at(-1).time, id=`gradient-${++chartId}`, color=key==='load'?'#74dac3':'#92a7ff';
  const x=t => end>start ? left+(t-start)/(end-start)*(right-left) : (left+right)/2, y=v => bottom-v/max*(bottom-top);
  const segments=[]; let segment=[], previous=null;
  samples.forEach(point => {
    if (!Number.isFinite(point[key]) || (previous!==null && point.time-previous>100)) { if(segment.length) segments.push(segment);segment=[]; }
    if(Number.isFinite(point[key])) segment.push([x(point.time),y(point[key])]);
    previous=point.time;
  });
  if(segment.length) segments.push(segment);
  const grid=compact?'':[0,.5,1].map(r=>`<line x1="${left}" y1="${y(max*r)}" x2="${right}" y2="${y(max*r)}" class="grid-line"/><text x="0" y="${y(max*r)+4}" class="axis-label">${num(max*r)}</text>`).join('');
  const paths=segments.map(points=>`<polygon points="${points[0][0]},${bottom} ${points.map(p=>p.join(',')).join(' ')} ${points.at(-1)[0]},${bottom}" fill="url(#${id})"/><polyline points="${points.map(p=>p.join(',')).join(' ')}" fill="none" stroke="${color}" stroke-width="${compact?2:2.4}" stroke-linejoin="round" stroke-linecap="round"/>${points.length===1?`<circle cx="${points[0][0]}" cy="${points[0][1]}" r="3" fill="${color}"/>`:''}`).join('');
  return `<svg class="chart ${compact?'compact-chart':''}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Historial de ${key==='load'?'carga':'latencia TCP en milisegundos'}: de ${esc(timeLabel(start))} a ${esc(timeLabel(end))}"><defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop stop-color="${color}" stop-opacity=".22"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>${grid}${paths}${compact?'':`<text x="${left}" y="174" class="axis-label">${esc(timeLabel(start))}</text><text x="${right}" y="174" text-anchor="end" class="axis-label">${esc(timeLabel(end))}</text>`}</svg>`;
}
function fleetHistory() {
  const groups=new Map();
  data.servers.forEach(s => (s.history||[]).slice(-120).forEach(h => {
    if(Number.isFinite(h.latency)) { const t=Math.floor(h.time/60)*60; if(!groups.has(t)) groups.set(t,[]); groups.get(t).push(h.latency); }
  }));
  return [...groups].sort((a,b)=>a[0]-b[0]).map(([time,values])=>({time,latency:mean(values)}));
}
function chartCard(server,key) {
  const history=visibleHistory(server), values=history.map(h=>h[key]).filter(Number.isFinite),load=key==='load';
  return `<section class="chart-card"><div class="card-heading"><div><p class="card-kicker">${load?'RENDIMIENTO':'RED'}</p><h3>${load?'Carga del servidor':'Latencia TCP'}</h3></div><span class="chart-current ${load?'mint-text':'blue-text'}">${num(server[key])}${load?'':'<small> ms</small>'}</span></div>${graph(history,key)}<div class="chart-stats"><span><i class="legend-dot ${load?'mint':'blue'}"></i>${load?'Carga media · 1 minuto':'Tiempo de conexión TCP'}</span><span>Media <strong>${num(mean(values))}${load?'':' ms'}</strong></span><span>Pico <strong>${values.length?num(Math.max(...values)):'—'}${load?'':' ms'}</strong></span></div></section>`;
}
function resource(label,value,extra,color) {
  return `<div class="resource"><div><span>${label}</span><strong class="${value>=90?'amber-text':''}">${pct(value)}</strong></div>${bar(value,color)}${extra?`<small>${extra}</small>`:''}</div>`;
}
function details(server) {
  const history=server.history||[], beats=history.slice(-60), range=ranges.get(server.id)||2, whm=safeURL(server.whmUrl),cpanel=safeURL(server.cpanelUrl);
  return `<div class="detail" id="detail-${esc(server.id)}"><div class="detail-top"><span>${icon('activity')}Actividad del servidor</span><div class="range-control" aria-label="Periodo de las gráficas">${[2,24].map(hours=>`<button data-range="${hours}" data-server="${esc(server.id)}" class="${hours===range?'active':''}" aria-pressed="${hours===range}">${hours===2?'2 horas':'24 horas'}</button>`).join('')}</div></div><div class="chart-grid">${chartCard(server,'load')}${chartCard(server,'latency')}</div><div class="detail-bottom-grid"><section class="resources-card"><div class="card-heading"><div><p class="card-kicker">CAPACIDAD</p><h3>Uso de recursos</h3></div>${icon('disk')}</div>${resource('Disco',server.disk,server.diskUsedGb==null?'':`${num(server.diskUsedGb)} / ${num(server.diskTotalGb)} GB · ${esc(server.mount||'/')}`,'mint')}${resource('Memoria RAM',server.ram,'','blue')}${resource('Procesador',server.cpu,'','purple')}<div class="boot-time">${icon('clock')}Tiempo encendido<strong>${server.bootSeconds==null?'—':num(server.bootSeconds/86400)+' días'}</strong></div></section><section class="availability-card"><div class="card-heading"><div><p class="card-kicker">CONTINUIDAD</p><h3>Disponibilidad</h3></div><span class="chart-current ${server.status==='down'?'red-text':'mint-text'}">${pct(server.uptime)}</span></div><div class="heartbeats" aria-label="Últimas comprobaciones de disponibilidad">${beats.length?beats.map(b=>`<span class="beat ${b.ok?'good':'bad'}" tabindex="0" aria-label="${esc(new Date(b.time*1000).toLocaleString('es-CO'))}: ${b.ok?'disponible':'sin conexión'}" data-tooltip="${esc(timeLabel(b.time))} · ${b.ok?'Disponible':'Sin conexión'}"></span>`).join(''):'<span class="beat unknown"></span>'}</div><div class="heartbeat-labels"><span>${beats.length} comprobaciones recientes</span><span>Ahora</span></div><div class="service-list">${Object.entries(server.services||{}).map(([name,ok])=>`<div class="service"><span class="status-dot ${ok?'':'down'}"></span><span>${esc(name)}</span><strong class="${ok?'mint-text':'red-text'}">${ok?'Accesible':'Sin conexión'}</strong></div>`).join('')}</div><p class="check-note ${server.error?'amber-text':''}">${icon(server.error?'warning':'check')}${esc(server.error||'Comprobación completada')}</p></section></div><div class="detail-actions"><div class="external-links">${!data.demo&&whm?`<a href="${esc(whm)}" target="_blank" rel="noopener noreferrer">Abrir WHM ${icon('arrow')}</a>`:''}${!data.demo&&cpanel?`<a href="${esc(cpanel)}" target="_blank" rel="noopener noreferrer">cPanel ${icon('arrow')}</a>`:''}</div><span class="checked-time">${server.checkedAt?'Revisado a las '+timeLabel(server.checkedAt):'Primera comprobación pendiente'}</span><button class="text-button" data-history="${esc(server.id)}">${icon('download')}Exportar CSV</button></div></div>`;
}
function rowMetric(label,value,progress,color='') {
  return `<span class="metric ${color}" data-label="${label}"><span>${value}</span>${progress!==undefined?bar(progress):''}</span>`;
}
function serverRow(server) {
  const open=expanded.has(server.id), host=serverHost(server)||'WHM / cPanel';
  return `<article class="server ${open?'is-open':''}" data-status="${esc(server.status)}"><div class="server-row-wrap"><button class="row server-row" data-expand="${esc(server.id)}" aria-expanded="${open}" aria-controls="detail-${esc(server.id)}"><span class="server-identity"><span class="server-icon ${esc(server.status)}">${icon('servers')}</span><span class="server-name"><strong>${esc(server.name)}</strong><small><span class="status-dot ${esc(server.status)}"></span>${esc(statusName(server.status))}<span class="host-address"> · ${esc(host)}</span></small></span></span>${rowMetric('Disco',pct(server.disk),server.disk,server.disk>=90?'amber-text':'')}${rowMetric('Carga',num(server.load),undefined,server.load>=6?'amber-text':'')}${rowMetric('CPU',pct(server.cpu),server.cpu)}${rowMetric('RAM',pct(server.ram),server.ram)}${rowMetric('Uptime',pct(server.uptime),undefined,server.status==='down'?'red-text':'mint-text')}${rowMetric('Latencia',server.latency==null?'—':`${num(server.latency)} <small>ms</small>`)}<span class="expand-icon">${icon('chevron')}</span></button>${!data.demo?`<button class="icon-button server-edit" data-edit="${esc(server.id)}" aria-label="Editar ${esc(server.name)}" title="Editar servidor">${icon('edit')}</button>`:''}</div>${open?details(server):`<div id="detail-${esc(server.id)}" hidden></div>`}</article>`;
}
function emptyState(filtered=false) {
  return `<div class="empty-state"><span class="empty-illustration">${icon(filtered?'search':'servers')}<span class="empty-orbit"></span></span><p class="eyebrow">${filtered?'AJUSTA TU BÚSQUEDA':'TODO EMPIEZA CON UN SERVIDOR'}</p><h3>${filtered?'No encontramos coincidencias.':'Un lugar para toda tu infraestructura.'}</h3><p>${filtered?'Prueba otro nombre, dirección o estado.':'Conecta tu primer servidor WHM para seguir su carga, recursos y disponibilidad.'}</p><button class="${filtered?'secondary':'primary'}" ${filtered?'data-reset-filter':'data-add-server'}>${icon(filtered?'refresh':'plus')}${filtered?'Limpiar filtros':'Conectar mi primer servidor'}</button><small>${filtered?'':'Comprobaciones automáticas cada 60 segundos'}</small></div>`;
}
function renderSummary() {
  const servers=data.servers,online=servers.filter(s=>s.status!=='down'),alerts=servers.filter(s=>s.status!=='healthy'),samples=servers.flatMap(s=>s.history||[]),uptime=samples.length?100*samples.filter(s=>s.ok).length/samples.length:null;
  const cards=[['servers',servers.length,'Servidores','Toda tu infraestructura',''],['activity',online.length,'En línea','Responden a la conexión TCP','mint'],['bell',alerts.length,'Necesitan atención',alerts.length?'Revisa las alertas activas':'Sin alertas activas',alerts.length?'amber':''],['shield',pct(uptime),'Disponibilidad','Muestras registradas · 24 h','blue']];
  $('#summary').innerHTML=cards.map(([name,value,label,note,tone],i)=>`<article class="summary-card ${tone}"><div class="summary-top"><span>${label}</span><span class="summary-icon">${icon(name)}</span></div><strong class="summary-value">${value}</strong><div class="summary-note">${i===1?'<span class="status-dot"></span>':''}${note}</div></article>`).join('');
  $('#serverCount').textContent=servers.length;$('#alertBadge').textContent=alerts.length;$('#alertBadge').hidden=!alerts.length;$('#listCount').textContent=servers.length;
  renderPopup(alerts);
}
function setPopup(open,focus=false) {
  $('#alertsPopup').hidden=!open;$('#alertsToggle').setAttribute('aria-expanded',String(open));
  if(open&&focus)$('#closeAlerts').focus({preventScroll:true});
}
function renderPopup(alerts) {
  $('#popupBadge').textContent=alerts.length;$('#popupBadge').hidden=!alerts.length;
  $('#popupDescription').textContent=alerts.length?`${alerts.length} ${alerts.length===1?'servidor requiere':'servidores requieren'} atención`:'Sin alertas activas';
  $('#popupContent').innerHTML=alerts.length?alerts.map(s=>`<article class="popup-alert"><span class="status-dot ${s.status==='down'?'down':'warning'}"></span><div><h3>${esc(s.name)}</h3><p>${esc(s.error||(s.disk>=90?'El uso de disco supera el 90%.':'Revisa los recursos o los servicios del servidor.'))}</p><button class="text-button" data-open="${esc(s.id)}">Revisar servidor ${icon('arrow')}</button></div></article>`).join(''):`<div class="popup-clear">${icon('shield')}<p>${data.servers.length?'Todos los servidores están operativos.':'Conecta un servidor para comenzar.'}</p></div>`;
  $('#fleetLatency').innerHTML=`${num(mean(data.servers.map(s=>s.latency).filter(Number.isFinite)))} <small>ms</small>`;$('#fleetChart').innerHTML=graph(fleetHistory(),'latency',true);
  const signature=JSON.stringify(alerts.map(s=>[s.id,s.status,s.error]).sort((a,b)=>a[0].localeCompare(b[0])));
  if(signature!==alertSignature&&alerts.length)setPopup(true);
  alertSignature=signature;
}
function renderList() {
  const focus=document.activeElement?.dataset,query=$('#search').value.trim().toLowerCase(),filter=$('#filter').value;
  const servers=data.servers.filter(s=>`${s.name} ${serverHost(s)}`.toLowerCase().includes(query)&&(filter==='all'||s.status===filter));
  $('#serverList').innerHTML=servers.map(serverRow).join('')||emptyState(data.servers.length>0);
  if(focus?.expand)[...document.querySelectorAll('[data-expand]')].find(b=>b.dataset.expand===focus.expand)?.focus({preventScroll:true});
  if(focus?.range)[...document.querySelectorAll('[data-range]')].find(b=>b.dataset.server===focus.server&&b.dataset.range===focus.range)?.focus({preventScroll:true});
}
function renderView() {
  const title={servers:'Servidores',monitor:'Monitorización',alerts:'Alertas',settings:'Ajustes'}[view];
  $('#title').textContent=title;$('#breadcrumb').textContent=title;document.title=`ServerPanel · ${title}`;
  document.querySelectorAll('nav button').forEach(b=>{b.classList.toggle('selected',b.dataset.view===view);if(b.dataset.view===view)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
  const list=['servers','monitor'].includes(view);$('#serversView').hidden=!list;$('#otherView').hidden=list;
  if(view==='alerts') {
    const alerts=data.servers.filter(s=>s.status!=='healthy');
    $('#otherView').innerHTML=alerts.length?`<div class="alerts-grid">${alerts.map(s=>`<article class="alert-card"><div class="alert-card-top"><span class="alert-icon ${s.status==='down'?'down':'warning'}">${icon('warning')}</span><span class="status-chip ${s.status==='down'?'down':'warning'}">${statusName(s.status)}</span></div><h2>${esc(s.name)}</h2><p>${esc(s.error||(s.disk>=90?'El uso de disco supera el 90%.':'La carga o los recursos están cerca de su límite.'))}</p><button class="secondary" data-open="${esc(s.id)}">Revisar servidor ${icon('arrow')}</button></article>`).join('')}</div>`:`<div class="all-clear"><span>${icon('shield')}</span><p class="eyebrow">SIN ALERTAS ACTIVAS</p><h2>${data.servers.length?'Todo en orden.':'Listo para empezar.'}</h2><p>${data.servers.length?'Tus servidores no tienen alertas activas.':'Cuando conectes tus servidores, verás aquí los destinos que requieren atención.'}</p></div>`;
  }
  if(view==='settings')$('#otherView').innerHTML=`<div class="settings-grid">${[['clock','Monitorización continua','El servicio comprueba los destinos cada 60 segundos, incluso con el navegador cerrado. Esta página consulta sus resultados cada minuto.','60 s'],['shield','Acceso protegido','Sesiones de 24 horas, contraseña con hash y acciones protegidas. Las credenciales de los servidores permanecen en el servicio.','24 h'],['activity','Métricas con su fuente','WHM proporciona la carga. El recolector Linux añade CPU, RAM, disco y tiempo encendido. Las métricas sin fuente aparecen como —.','WHM + Linux'],['disk','Historial persistente','Se conservan muestras durante 30 días. Las gráficas muestran las últimas 24 horas disponibles; puedes exportarlas en CSV.','30 días']].map(([name,title,copy,value])=>`<article class="settings-card"><span class="settings-icon">${icon(name)}</span><strong class="settings-value">${value}</strong><h2>${title}</h2><p>${copy}</p></article>`).join('')}</div>`;
}
function render(){renderSummary();renderList();renderView();}
function notice(message,tone=''){$('#notice').textContent=message;$('#notice').hidden=!message;$('#notice').className=`notice ${tone}`;}
function openDialog() {
  dialogRequest++;editingId=null;const form=$('#serverForm');form.reset();form.querySelector('details').open=false;
  $('#formError').textContent='';$('#dialogTitle').textContent='Conectar un servidor';$('#dialogEyebrow').textContent='AMPLÍA TU INFRAESTRUCTURA';
  $('#dialogIntro').textContent='Añade un destino WHM y empieza a seguir su disponibilidad.';
  $('#clearWhmLabel').hidden=true;$('#clearMetricsLabel').hidden=true;
  form.elements.whmToken.placeholder='Para consultar la carga del servidor';form.elements.metricsToken.placeholder='';
  $('#saveServer').innerHTML=icon('plus')+'Conectar y monitorizar';$('#saveServer').disabled=false;$('#serverDialog').showModal();
}
async function editServer(id) {
  openDialog();editingId=id;const request=dialogRequest;$('#saveServer').disabled=true;
  $('#dialogTitle').textContent='Editar servidor';$('#dialogEyebrow').textContent='CONFIGURACIÓN DEL SERVIDOR';
  $('#dialogIntro').textContent='Deja los tokens vacíos para conservar los actuales. El historial se mantiene.';
  $('#saveServer').innerHTML=icon('check')+'Guardar cambios';
  try {
    const response=await fetch('/api/servers/'+encodeURIComponent(id),{cache:'no-store'});
    if(response.status===401){window.location.replace('/login');return;}
    const settings=await response.json();if(!response.ok)throw Error(settings.error||'No se pudo cargar el servidor.');
    if(request!==dialogRequest||!$('#serverDialog').open)return;
    const form=$('#serverForm');['name','host','whm_user','whm_port','metrics_url'].forEach(key=>form.elements[key].value=settings[key]??'');
    form.elements.whmToken.placeholder=settings.hasWhmToken?'Token guardado · vacío para conservarlo':'Sin token guardado';
    form.elements.metricsToken.placeholder=settings.hasMetricsToken?'Token guardado · vacío para conservarlo':'Sin token guardado';
    $('#clearWhmLabel').hidden=!settings.hasWhmToken;$('#clearMetricsLabel').hidden=!settings.hasMetricsToken;
    form.querySelector('details').open=Boolean(settings.metrics_url);$('#saveServer').disabled=false;
  } catch(error){if(request===dialogRequest)$('#formError').textContent=error.message;}
}
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;setTimeout(()=>$('#toast').hidden=true,5000);}
async function refresh() {
  if(busy)return;busy=true;$('#refresh').disabled=true;$('#refresh').classList.add('refreshing');
  try {
    const r=await fetch('/api/status',{cache:'no-store'});if(r.status===401){window.location.replace('/login');return;}if(!r.ok)throw Error();data=await r.json();
    if(firstLoad&&data.servers.length){expanded.add(data.servers[0].id);firstLoad=false;}render();remaining=60;
    $('#lastUpdate').textContent=`Actualizado ${new Date().toLocaleTimeString('es-CO',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}`;
    $('#mode').textContent=data.demo?'Demostración':data.monitorError?'Monitor con error':'En vivo';$('#livePill').classList.toggle('offline',Boolean(data.monitorError));
    notice(data.monitorError||(data.demo?'Vista de demostración. Estas métricas son ejemplos, no corresponden a servidores reales.':''),data.monitorError?'error':'');
  }catch{notice('No se pudo consultar el servicio. La última vista puede contener datos desactualizados.','error');$('#mode').textContent='Sin conexión';$('#livePill').classList.add('offline');}
  finally{busy=false;$('#refresh').disabled=false;$('#refresh').classList.remove('refreshing');}
}
function exportHistory(id) {
  const server=data.servers.find(s=>s.id===id);if(!server)return;
  const csv='fecha_utc,en_linea,latencia_ms,carga\n'+(server.history||[]).map(h=>[new Date(h.time*1000).toISOString(),h.ok?1:0,h.latency??'',h.load??''].join(',')).join('\n');
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=id+'-historial.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Historial exportado en CSV.');
}
document.addEventListener('click',event=>{
  const b=event.target.closest('button');if(!b)return;
  if(b.dataset.expand){expanded.has(b.dataset.expand)?expanded.delete(b.dataset.expand):expanded.add(b.dataset.expand);renderList();}
  if(b.dataset.view){view=b.dataset.view;if(view==='monitor'){data.servers.forEach(s=>expanded.add(s.id));renderList();}renderView();}
  if(b.dataset.open){setPopup(false);view='servers';expanded.add(b.dataset.open);renderList();renderView();[...document.querySelectorAll('[data-expand]')].find(el=>el.dataset.expand===b.dataset.open)?.scrollIntoView({block:'start',behavior:'smooth'});}
  if(b.dataset.range){ranges.set(b.dataset.server,Number(b.dataset.range));renderList();}
  if(b.dataset.history)exportHistory(b.dataset.history);
  if(b.dataset.edit)editServer(b.dataset.edit);
  if(b.hasAttribute('data-toggle-alerts'))setPopup($('#alertsPopup').hidden,true);
  if(b.hasAttribute('data-add-server'))openDialog();
  if(b.hasAttribute('data-reset-filter')){$('#search').value='';$('#filter').value='all';renderList();}
});
$('#search').addEventListener('input',renderList);$('#filter').addEventListener('change',renderList);$('#refresh').addEventListener('click',refresh);$('#addServer').addEventListener('click',openDialog);$('#closeDialog').addEventListener('click',()=>$('#serverDialog').close());
$('#alertsToggle').addEventListener('click',()=>setPopup($('#alertsPopup').hidden,true));
$('#closeAlerts').addEventListener('click',()=>{setPopup(false);$('#alertsToggle').focus({preventScroll:true});});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!$('#serverDialog').open&&!$('#alertsPopup').hidden){setPopup(false);$('#alertsToggle').focus({preventScroll:true});}});
$('#serverDialog').addEventListener('close',()=>{dialogRequest++;editingId=null;$('#serverForm').reset();});
$('#serverForm').addEventListener('submit',async event=>{
  event.preventDefault();$('#saveServer').disabled=true;$('#formError').textContent='';
  const id=editingId;
  try {
    const payload=Object.fromEntries(new FormData(event.target));
    ['clearWhmToken','clearMetricsToken'].forEach(key=>payload[key]=event.target.elements[key].checked);
    const response=await fetch('/api/servers'+(id?'/'+encodeURIComponent(id):''),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(payload)}),result=await response.json();
    if(response.status===401){window.location.replace('/login');return;}
    if(!response.ok)throw Error(result.error||'No se pudo guardar el servidor.');
    $('#serverDialog').close();
    if(id){const server=data.servers.find(s=>s.id===id);if(server){server.name=payload.name;server.host=payload.host;server.whmUrl=`https://${payload.host}:${payload.whm_port}`;}renderList();}
    toast(id?'Cambios guardados. Se comprobará la nueva configuración en unos segundos.':'Servidor conectado. Su primera comprobación aparecerá en unos segundos.');setTimeout(refresh,12000);
  }
  catch(error){$('#formError').textContent=error.message;}finally{$('#saveServer').disabled=false;}
});
$('#logout').addEventListener('click',async()=>{try{const response=await fetch('/api/logout',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:'{}'});if(!response.ok&&response.status!==401)throw Error();window.location.replace('/login');}catch{notice('No se pudo cerrar la sesión. Vuelve a intentarlo.','error');}});
function updateClock(){const now=new Date();$('#clock').textContent=now.toLocaleString('es-CO');$('#today').textContent=now.toLocaleDateString('es-CO',{day:'numeric',month:'short',year:'numeric'});$('#countdown').textContent=`Próxima consulta en ${Math.max(0,remaining)} s`;}
setInterval(()=>{remaining--;updateClock();if(remaining<=0){remaining=60;refresh();}},1000);updateClock();
async function initialize(){try{const response=await fetch('/api/session',{cache:'no-store'});if(response.status===401){window.location.replace('/login');return;}if(!response.ok)throw Error();const session=await response.json();csrf=session.csrf;$('#accountName').innerHTML=`${esc(session.username||'Administrador')}<small>Sesión de 24 horas</small>`;$('#avatar').textContent=(session.username||'A').slice(0,1).toUpperCase();await refresh();}catch{notice('No se pudo verificar tu sesión. Recarga la página para volver a intentarlo.','error');}}
initialize();
