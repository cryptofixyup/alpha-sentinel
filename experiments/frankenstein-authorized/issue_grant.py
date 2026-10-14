"""Trusted operator CLI; never expose to the agent as a tool."""
import argparse
import json
import os
from pathlib import Path
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
    Path(args.output).write_text(json.dumps(grant, indent=2), encoding='utf-8')
finally:
    cp.close()
print('Grant created for exact query. Keep key and grant out of model context.')
