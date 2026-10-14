import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from authority import AuthorityError, ControlPlane, ScopeContract

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
        from unittest.mock import patch
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
    def test_persistence_across_restart(self):
        grant = self.cp.issue('tenant-a','web_search',{'query':'test'})
        self.execute(grant)
        self.cp.close()
        self.cp = ControlPlane(b'k'*32, Path(self.tmp.name)/'grants.db', ScopeContract(frozenset({'web_search'}),'tenant-a'))
        with self.assertRaises(AuthorityError): self.execute(grant)

if __name__ == '__main__': unittest.main()
