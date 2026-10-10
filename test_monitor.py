import json
import tempfile
import threading
import http.client
import unittest
from pathlib import Path
from unittest.mock import patch
import server


class MonitorTests(unittest.TestCase):
    def test_edit_preserves_id_history_ports_and_blank_credentials(self):
        with tempfile.TemporaryDirectory(dir=server.ROOT) as directory:
            config=Path(directory)/'config.json'
            config.write_text('[]')
            with patch.object(server,'CONFIG',config),patch.object(server,'DATA',Path(directory)/'data'):
                identifier=server.add_server({'host':'one.example.com','name':'Uno','whmToken':'whm-original','metricsToken':'metrics-original','metrics_url':'https://one.example.com/metrics'})
                with server.connect_db() as db:
                    db.execute('INSERT INTO checks VALUES (?, ?, ?, ?, ?)',(identifier,123,1,10,2))
                server.update_server(identifier,{'name':'Nuevo nombre','host':'renamed.example.com','whm_port':'2099','whm_user':'admin','whmToken':'','metricsToken':''})
                cfg=server.read_config()[0]
                self.assertEqual(cfg['id'],identifier)
                self.assertEqual(cfg['host'],'renamed.example.com')
                self.assertEqual(cfg['ports'],{'HTTPS':443,'WHM':2099,'cPanel':2083,'SSH':22})
                self.assertEqual(json.loads((server.DATA/'secrets.json').read_text())[identifier],{'whmToken':'whm-original','metricsToken':'metrics-original'})
                with server.connect_db() as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM checks WHERE server=?',(identifier,)).fetchone()[0],1)
                settings=server.server_settings(identifier)
                self.assertEqual(settings['name'],'Nuevo nombre')
                self.assertTrue(settings['hasWhmToken'])
                self.assertTrue(settings['hasMetricsToken'])
                self.assertNotIn('original',json.dumps(settings))

    def test_edit_rotates_and_explicitly_removes_credentials(self):
        with tempfile.TemporaryDirectory(dir=server.ROOT) as directory:
            config=Path(directory)/'config.json';config.write_text('[]')
            with patch.object(server,'CONFIG',config),patch.object(server,'DATA',Path(directory)/'data'):
                identifier=server.add_server({'host':'one.example.com','whmToken':'old','metricsToken':'old-metrics','metrics_url':'https://one.example.com/metrics'})
                server.update_server(identifier,{'whmToken':'new'})
                self.assertEqual(json.loads((server.DATA/'secrets.json').read_text())[identifier]['whmToken'],'new')
                server.update_server(identifier,{'clearWhmToken':True,'clearMetricsToken':True})
                cfg=server.read_config()[0]
                self.assertNotIn('whm_token_env',cfg)
                self.assertNotIn('metrics_url',cfg)
                self.assertNotIn('metrics_token_env',cfg)
                self.assertEqual(json.loads((server.DATA/'secrets.json').read_text())[identifier],{})

    def test_invalid_edit_leaves_existing_config_and_secrets_unchanged(self):
        with tempfile.TemporaryDirectory(dir=server.ROOT) as directory:
            config=Path(directory)/'config.json';config.write_text('[]')
            with patch.object(server,'CONFIG',config),patch.object(server,'DATA',Path(directory)/'data'):
                identifier=server.add_server({'host':'one.example.com','whmToken':'original'})
                server.add_server({'host':'two.example.com'})
                before=[(server.DATA/name).read_bytes() for name in ['servers.json','secrets.json']]
                for payload in [{'host':'two.example.com'},{'whm_port':0},{'host':'bad/path'},{'whmToken':'bad\ntoken'},{'metrics_url':'http://one.example.com'},{'metrics_url':'https://one.example.com/metrics'}]:
                    with self.assertRaises(ValueError):server.update_server(identifier,payload)
                self.assertEqual(before,[(server.DATA/name).read_bytes() for name in ['servers.json','secrets.json']])
                with self.assertRaises(server.ServerNotFound):server.update_server('missing',{})

    def test_edit_api_requires_session_csrf_and_authorized_origin(self):
        current={'username':'admin','csrf':'test-csrf'}
        with patch.object(server.Handler,'current_session',return_value=current),patch.dict(server.os.environ,{'ALLOWED_ORIGIN':'https://monitor.example.com'}),patch.object(server,'server_settings',return_value={'id':'one','hasWhmToken':True}),patch.object(server,'update_server',return_value='one') as update:
            httpd=server.BoundedHTTPServer(('127.0.0.1',0),server.Handler)
            thread=threading.Thread(target=httpd.serve_forever,daemon=True);thread.start()
            def request(method,headers=None):
                conn=http.client.HTTPConnection('127.0.0.1',httpd.server_port,timeout=3)
                conn.request(method,'/api/servers/one','{}' if method=='POST' else None,headers or {})
                response=conn.getresponse();body=response.read();conn.close();return response.status,body
            try:
                self.assertEqual(request('GET')[0],200)
                headers={'Origin':'https://monitor.example.com','Content-Type':'application/json'}
                self.assertEqual(request('POST',headers)[0],403)
                headers['X-CSRF-Token']='test-csrf'
                self.assertEqual(request('POST',headers)[0],200)
                headers['Origin']='https://untrusted.example.com'
                self.assertEqual(request('POST',headers)[0],403)
                with patch.object(server.Handler,'current_session',return_value=None):
                    self.assertEqual(request('GET')[0],401)
                    headers['Origin']='https://monitor.example.com'
                    self.assertEqual(request('POST',headers)[0],401)
                self.assertEqual(update.call_count,1)
            finally:httpd.shutdown();httpd.server_close();thread.join()

    def test_add_server_separates_secrets_and_rejects_duplicates(self):
        with tempfile.TemporaryDirectory(dir=server.ROOT) as directory:
            config=Path(directory)/'config.json'
            config.write_text('[]')
            with patch.object(server,'CONFIG',config),patch.object(server,'DATA',Path(directory)/'data'):
                identifier=server.add_server({'host':'one.example.com','name':'Uno','whmToken':'private-test-token'})
                self.assertNotIn('private-test-token',(server.DATA/'servers.json').read_text())
                self.assertEqual(json.loads((server.DATA/'secrets.json').read_text())[identifier]['whmToken'],'private-test-token')
                with self.assertRaises(ValueError):
                    server.add_server({'host':'one.example.com'})
                with self.assertRaises(ValueError):
                    server.add_server({'host':'two.example.com','metrics_url':'http://example.com/metrics'})

    def test_closed_primary_service_is_down(self):
        with patch.object(server,'tcp_check', return_value=(False,None)):
            item = server.check_server({'id':'one','host':'example.com'})
        self.assertEqual(item['status'],'down')
        self.assertIsNone(item['cpu'])
        self.assertFalse(item['_ok'])

    def test_whm_load_and_collector_metrics(self):
        def response(url, headers):
            if '/json-api/' in url:
                return {'metadata':{'result':1}, 'data':{'one':'2.42'}}
            return {'disk':91,'ram':40,'cpu':10,'load':1,'diskUsedGb':910,'diskTotalGb':1000}
        with patch.object(server,'tcp_check',return_value=(True,15)), patch.object(server,'fetch_json',side_effect=response), patch.dict(server.os.environ,{'TOKEN':'secret','METRICS':'secret'}):
            item=server.check_server({'id':'one','host':'example.com','whm_token_env':'TOKEN','metrics_token_env':'METRICS','metrics_url':'https://metrics.example.com/metrics'})
        self.assertEqual(item['load'],2.42)
        self.assertEqual(item['disk'],91)
        self.assertEqual(item['status'],'warning')
        self.assertNotIn('secret',json.dumps(item))

    def test_api_failure_is_warning_without_leaking_details(self):
        with patch.object(server,'tcp_check',return_value=(True,15)), patch.object(server,'fetch_json',side_effect=ValueError('sensitive-token')),patch.dict(server.os.environ,{'TOKEN':'secret'}):
            item=server.check_server({'id':'one','host':'example.com','whm_token_env':'TOKEN'})
        self.assertEqual(item['status'],'warning')
        self.assertIsNone(item['load'])
        self.assertNotIn('sensitive-token',json.dumps(item))

    def test_history_persists_and_calculates_uptime(self):
        with tempfile.TemporaryDirectory(dir=server.ROOT) as directory:
            config=Path(directory)/'servers.json'
            config.write_text('[{"id":"one","host":"example.com"}]')
            with patch.object(server,'CONFIG',config),patch.object(server,'DATA',Path(directory)/'data'),patch.dict(server.os.environ,{'DEMO':'0'}):
                with patch.object(server,'tcp_check',return_value=(True,10)):
                    server.cycle()
                with patch.object(server,'tcp_check',return_value=(False,None)):
                    server.cycle()
                self.assertEqual(server.STATE['servers'][0]['uptime'],50)
                self.assertEqual(len(server.STATE['servers'][0]['history']),2)

    def test_invalid_config_and_nonfinite_values(self):
        for cfg in [[{'id':'../x','host':'example.com'}],[{'id':'one','host':'example.com/path'}],[{'id':'one','host':'example.com','ports':{'WHM':0}}]]:
            with self.assertRaises(ValueError):
                server.validate_config(cfg)
        self.assertIsNone(server.number('nan'))


if __name__=='__main__':
    unittest.main()
