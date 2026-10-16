import concurrent.futures
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from authority import AuthorityError, ControlPlane, ScopeContract
from config_flags import env_opt_in

class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cp = ControlPlane(b'k' * 32, Path(self.tmp.name) / 'grants.db', ScopeContract(frozenset({'web_search'}), 'tenant-a'))
        self.calls = 0
    def tearDown(self):
        self.cp.close()
        self.tmp.cleanup()
    def execute(self, grant, args=None):
        def fn(query):
            self.calls += 1
            return 'success'
        return self.cp.execute(grant, 'tenant-a', 'web_search', args or {'query':'test'}, fn)
    def test_valid_once_and_replay_denied(self):
        grant = self.cp.issue('tenant-a','web_search',{'query':'test'})
        self.assertEqual(self.execute(grant), 'success')
        self.assertEqual(self.cp.evidence(grant['body']['nonce'])[0], 'COMPLETED')
        with self.assertRaises(AuthorityError): self.execute(grant)
        self.assertEqual(self.calls, 1)
    def test_tampering_denied(self):
        grant = self.cp.issue('tenant-a','web_search',{'query':'test'})
        with self.assertRaises(AuthorityError): self.execute(grant, {'query':'other'})
        self.assertEqual(self.calls, 0)
    def test_signature_denied(self):
        grant = self.cp.issue('tenant-a','web_search',{'query':'test'})
        grant['signature'] = '0'*64
        with self.assertRaises(AuthorityError): self.execute(grant)
    def test_scope_denied(self):
        with self.assertRaises(AuthorityError): self.cp.issue('tenant-a','shell',{})
        with self.assertRaises(AuthorityError): self.cp.issue('other','web_search',{})
    def test_revoked_denied(self):
        grant = self.cp.issue('tenant-a','web_search',{'query':'test'})
        self.cp.revoke(grant['body']['nonce'])
        with self.assertRaises(AuthorityError): self.execute(grant)
    def test_expired_denied(self):
        with patch('authority.time.time', return_value=100):
            grant = self.cp.issue('tenant-a','web_search',{'query':'test'}, ttl=1)
        with patch('authority.time.time', return_value=101):
            with self.assertRaises(AuthorityError): self.execute(grant)
    def test_concurrent_single_effect(self):
        grant = self.cp.issue('tenant-a','web_search',{'query':'test'})
        def attempt(_):
            try: self.execute(grant); return True
            except AuthorityError: return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(attempt, range(16)))
        self.assertEqual(sum(outcomes), 1)
        self.assertEqual(self.calls, 1)
    def test_exception_preserves_uncertainty(self):
        grant = self.cp.issue('tenant-a','web_search',{'query':'test'})
        def fail(query): raise RuntimeError('response lost')
        with self.assertRaises(RuntimeError): self.cp.execute(grant,'tenant-a','web_search',{'query':'test'},fail)
        self.assertEqual(self.cp.evidence(grant['body']['nonce'])[0], 'UNKNOWN')
        with self.assertRaises(AuthorityError): self.execute(grant)
    def test_security_opt_in_is_fail_closed(self):
        name = 'FRANKENSTEIN_TEST_OPT_IN'
        false_like = ['', '0', 'false', 'no', 'off', 'typo', 'False ']
        for value in false_like:
            with self.subTest(value=value), patch.dict(os.environ, {name: value}, clear=False):
                self.assertFalse(env_opt_in(name))
        for value in ['1', 'true', 'yes', ' TRUE ', 'Yes']:
            with self.subTest(value=value), patch.dict(os.environ, {name: value}, clear=False):
                self.assertTrue(env_opt_in(name))

    @unittest.skipUnless(os.name == 'posix', 'POSIX permission semantics required')
    def test_issue_grant_file_is_owner_only(self):
        script = Path(__file__).resolve().parents[1] / 'issue_grant.py'
        output = Path(self.tmp.name) / 'grant.json'
        env = os.environ.copy()
        env['SENTINEL_AUTHORITY_KEY_HEX'] = (b'g' * 32).hex()
        env['SENTINEL_AUTHORITY_DB'] = str(Path(self.tmp.name) / 'cli.db')
        subprocess.run(
            [sys.executable, str(script), '--query', 'test', '--output', str(output), '--tenant', 'local'],
            check=True,
            cwd=str(script.parent),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)

    def test_persistence_across_restart(self):
        grant = self.cp.issue('tenant-a','web_search',{'query':'test'})
        self.execute(grant)
        self.cp.close()
        self.cp = ControlPlane(b'k'*32, Path(self.tmp.name)/'grants.db', ScopeContract(frozenset({'web_search'}),'tenant-a'))
        with self.assertRaises(AuthorityError): self.execute(grant)

if __name__ == '__main__': unittest.main()
