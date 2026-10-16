"""Trusted operator CLI; never expose to the agent as a tool."""
import argparse
import json
import os
from authority import ControlPlane, ScopeContract

parser = argparse.ArgumentParser()
parser.add_argument('--query', required=True)
parser.add_argument('--output', default='web_grant.json')
parser.add_argument('--tenant', default='local')
args = parser.parse_args()
key = bytes.fromhex(os.environ['SENTINEL_AUTHORITY_KEY_HEX'])
cp = ControlPlane(key, os.getenv('SENTINEL_AUTHORITY_DB','./authority.sqlite3'), ScopeContract(frozenset({'web_search'}), args.tenant))
try:
    grant = cp.issue(args.tenant, 'web_search', {'query': args.query}, ttl=300)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps(grant, indent=2))
finally:
    cp.close()
print('Grant created for exact query. Keep key and grant out of model context.')
