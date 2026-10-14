"""Offline tool-boundary integration tests; no model downloads or network calls.

The actual search_book/web_search function bodies are compiled from the source
AST with heavyweight framework decorators removed. This does not validate
LangGraph, ChromaDB, or Anthropic integration.
"""
import ast
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from authority import ControlPlane, ScopeContract

ROOT = Path(__file__).resolve().parents[1]

def load_tools():
    tree = ast.parse((ROOT / "frankenstein_agent.py").read_text(encoding="utf-8"))
    names = {"search_book", "web_search"}
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            node.decorator_list = []
            nodes.append(node)
    assert len(nodes) == 2, "tool definitions missing"
    ns = {"os": os, "json": json, "Path": Path, "KB": None,
          "ENABLE_WEB": False, "_web_search_uncached": lambda query: "UNEXPECTED"}
    exec(compile(ast.Module(body=nodes, type_ignores=[]),
                 str(ROOT / "frankenstein_agent.py"), "exec"), ns)
    return ns

class AgentIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "authority.db")
        self.grant_path = str(Path(self.tmp.name) / "grant.json")
        self.key = b"G" * 32
        self.cp = ControlPlane(self.key, self.db,
                               ScopeContract(frozenset({"web_search"}), "local"))
        self.addCleanup(self.cp.close)
        env = patch.dict(os.environ, {
            "SENTINEL_AUTHORITY_KEY_HEX": self.key.hex(),
            "SENTINEL_WEB_GRANT_FILE": self.grant_path,
            "SENTINEL_AUTHORITY_DB": self.db,
            "SENTINEL_TENANT": "local"})
        env.start()
        self.addCleanup(env.stop)
        self.ns = load_tools()
        self.calls = []
        def executor(query):
            self.calls.append(query)
            return "mock result for " + query
        self.ns["_web_search_uncached"] = executor

    def grant(self, query):
        grant = self.cp.issue("local", "web_search", {"query": query})
        Path(self.grant_path).write_text(json.dumps(grant), encoding="utf-8")
        return grant

    def test_book_retrieval_uses_kb(self):
        class KB:
            def format_results(self, query):
                return "Passage from Frankenstein: " + query
        self.ns["KB"] = KB()
        self.assertIn("Passage", self.ns["search_book"]("creature"))

    def test_book_without_kb_fails_explicitly(self):
        self.assertIn("not initialized", self.ns["search_book"]("creature"))

    def test_disabled_web_never_executes(self):
        self.grant("exact")
        self.assertIn("disabled", self.ns["web_search"]("exact"))
        self.assertEqual(self.calls, [])

    def test_enabled_without_grant_denies(self):
        self.ns["ENABLE_WEB"] = True
        self.assertIn("DENIED", self.ns["web_search"]("exact"))
        self.assertEqual(self.calls, [])

    def test_exact_grant_once_and_replay_denied(self):
        self.ns["ENABLE_WEB"] = True
        grant = self.grant("exact")
        self.assertEqual(self.ns["web_search"]("exact"), "mock result for exact")
        self.assertIn("DENIED", self.ns["web_search"]("exact"))
        self.assertEqual(self.calls, ["exact"])
        self.assertEqual(self.cp.evidence(grant["body"]["nonce"])[0], "COMPLETED")

    def test_modified_query_denied(self):
        self.ns["ENABLE_WEB"] = True
        self.grant("exact")
        self.assertIn("DENIED", self.ns["web_search"]("modified"))
        self.assertEqual(self.calls, [])

    def test_executor_failure_unknown_and_replay_denied(self):
        self.ns["ENABLE_WEB"] = True
        grant = self.grant("exact")
        def fail(query):
            self.calls.append(query)
            raise RuntimeError("response lost")
        self.ns["_web_search_uncached"] = fail
        with self.assertRaises(RuntimeError):
            self.ns["web_search"]("exact")
        self.assertEqual(self.cp.evidence(grant["body"]["nonce"])[0], "UNKNOWN")
        self.assertIn("DENIED", self.ns["web_search"]("exact"))
        self.assertEqual(self.calls, ["exact"])

    def test_restart_preserves_consumption(self):
        self.ns["ENABLE_WEB"] = True
        self.grant("exact")
        self.ns["web_search"]("exact")
        self.cp.close()
        self.cp = ControlPlane(self.key, self.db,
                               ScopeContract(frozenset({"web_search"}), "local"))
        self.assertIn("DENIED", self.ns["web_search"]("exact"))
        self.assertEqual(self.calls, ["exact"])

if __name__ == "__main__":
    unittest.main()
