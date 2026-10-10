import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import server


class MonitorTests(unittest.TestCase):
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
