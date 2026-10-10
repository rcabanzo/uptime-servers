import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import auth


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.path=Path(self.temp.name)
        self.patch=patch.object(auth,'DATA',self.path)
        self.patch.start()
        salt='a3'*32
        value=hashlib.pbkdf2_hmac('sha256',b'test-password',bytes.fromhex(salt),600000).hex()
        (self.path/'auth.json').write_text(json.dumps(dict(username='admin',salt=salt,hash=value,iterations=600000)))

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_login_cookie_and_revocation(self):
        result,status=auth.login('admin','test-password','192.0.2.1')
        self.assertEqual(status,200)
        cookie=auth.set_cookie(result['token'])
        for flag in ['Secure','HttpOnly','SameSite=Strict','Path=/']:
            self.assertIn(flag,cookie)
        self.assertIn('Max-Age=86400',cookie)
        self.assertIn('Max-Age=120',auth.set_cookie(result['token'],max_age=120))
        current=auth.session(cookie)
        self.assertEqual(current['username'],'admin')
        self.assertEqual(current['csrf'],result['csrf'])
        with auth.database() as conn:
            row=conn.execute('SELECT token FROM sessions').fetchone()
            self.assertNotEqual(row[0],result['token'])
        auth.logout(cookie)
        self.assertIsNone(auth.session(cookie))

    def test_invalid_password_then_rate_limit(self):
        for _ in range(5):
            self.assertEqual(auth.login('admin','wrong','192.0.2.2')[1],401)
        self.assertEqual(auth.login('admin','test-password','192.0.2.2')[1],429)
        self.assertEqual(auth.login('admin','test-password','192.0.2.3')[1],200)

    def test_expiration_and_forged_session(self):
        result,_=auth.login('admin','test-password','192.0.2.4')
        cookie=auth.set_cookie(result['token'])
        with patch.object(auth.time,'time',return_value=auth.time.time()+auth.LIFETIME+1):
            self.assertIsNone(auth.session(cookie))
        self.assertIsNone(auth.session('__Host-serverpanel='+'a'*43))

    def test_missing_credentials_fail_closed(self):
        (self.path/'auth.json').unlink()
        self.assertEqual(auth.login('admin','test-password','192.0.2.5')[1],503)


if __name__=='__main__':
    unittest.main()
