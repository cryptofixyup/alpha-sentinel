# Frankenstein RAG + Alpha Sentinel local authorization reference

## Scope
- `frankenstein_agent.py` retains the uploaded RAG architecture and tools.
- Web search now defaults **off**. When enabled, each exact query requires a signed, single-use grant from the trusted operator CLI.
- `authority.py` implements deny-by-default scope, HMAC-SHA256 payload binding, expiry, revocation, SQLite atomic nonce reservation, and durable terminal/uncertain outcomes.
- The agent has no grant-issuance tool. Corpus retrieval is read-only and remains available.

## Installation
Python 3.11+; use the dependency list in `frankenstein_agent.py` docstring. Copy `frankenstein.txt` beside the agent or set `FRANKENSTEIN_BOOK`.

```bash
python -m pip install -U langchain langchain-anthropic langchain-chroma langchain-huggingface langchain-text-splitters langgraph chromadb sentence-transformers rank-bm25 ddgs python-dotenv
python -m unittest discover -s tests -v
python frankenstein_agent.py
```

## Optional authorized web search
Set `FRANKENSTEIN_WEB_SEARCH=1`. Generate and protect a random 32-byte key (for example `python -c 'import secrets;print(secrets.token_hex(32))'`) and set `SENTINEL_AUTHORITY_KEY_HEX` to its hex representation. Protect it from agent prompts and tool outputs. Set `SENTINEL_WEB_GRANT_FILE` to the output path. In a trusted operator process:

```bash
python issue_grant.py --query 'Mary Shelley biography' --output web_grant.json
```

A grant is valid only for that exact query and one execution; arbitrary LLM-chosen queries are denied. The local CLI grant file is not an automated approval workflow. Do not expose the issuer or signing key as agent tools.

## Known limits (important)
- **Not an IETF-interoperable approval artifact.** HMAC is symmetric; the verifier also possesses the signing key. Use asymmetric signatures, key IDs, normative canonicalization, and test vectors for interoperability.
- SQLite nonce reservation prevents duplicate execution requests against this database. It **cannot guarantee exactly-once external effects** when a process crashes after the external tool performs an action. UNKNOWN/RESERVED require reconciliation, not automatic retries.
- `revoke()` does not stop an already reserved/running execution. Concurrent revocation/execution semantics need a stronger lease/transaction protocol.
- A completed evidence row records a digest of the returned string, not independent verification of external success. It is an execution receipt, not proof of external effect.
- Web results remain untrusted text. No prompt-injection or source authenticity guarantee is provided.
- Existing Chroma index consistency, model dependency compatibility, retrieval quality, and resource usage remain untested in this package.
- Grant file must be protected from untrusted local users. SQLite files need filesystem access controls.

## Verification
Nine unit tests exercise valid execution, replay, tampering, invalid signature, scope, revocation, expiry, concurrent replay, uncertainty, and restart persistence (nine test functions total). They use a mock tool, not real web or Anthropic calls.
