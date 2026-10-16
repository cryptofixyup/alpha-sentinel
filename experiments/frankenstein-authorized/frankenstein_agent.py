"""
Frankenstein Agent — performance-optimized single-file RAG agent.

Optimizations:
- Persistent Chroma + deterministic corpus/config fingerprinting.
- Hybrid dense + BM25 retrieval with O(n log k) lexical top-k selection.
- One reusable thread pool instead of creating an executor per query.
- LRU caching for repeated retrievals and web searches.
- Lazy optional cross-encoder loading.
- Deterministic chunk IDs and batched Chroma writes.
- Configurable embedding device/batch size and retrieval widths.
- Compact tool output to reduce LLM input tokens.
- Defensive startup/rebuild handling.
- Clean CLI with /reset, /stats, /quit.

Required:
    frankenstein.txt
    .env

Install:
    pip install -U langchain langchain-anthropic langchain-chroma \
      langchain-huggingface langchain-text-splitters langgraph chromadb \
      sentence-transformers rank-bm25 ddgs python-dotenv

.env:
    ANTHROPIC_API_KEY=...
    FRANKENSTEIN_MODEL=anthropic:claude-sonnet-4-6

Performance knobs:
    FRANKENSTEIN_EMBED_MODEL=BAAI/bge-m3
    FRANKENSTEIN_EMBED_DEVICE=cpu
    FRANKENSTEIN_EMBED_BATCH=64
    FRANKENSTEIN_CHUNK_SIZE=900
    FRANKENSTEIN_CHUNK_OVERLAP=120
    FRANKENSTEIN_DENSE_K=12
    FRANKENSTEIN_BM25_K=12
    FRANKENSTEIN_TOP_K=6
    FRANKENSTEIN_RRF_K=60
    FRANKENSTEIN_RERANK=0
    FRANKENSTEIN_RERANK_K=12
    FRANKENSTEIN_WEB_SEARCH=1
    FRANKENSTEIN_CACHE_SIZE=128
    FRANKENSTEIN_WEB_CACHE_SIZE=64
    FRANKENSTEIN_WEB_RESULTS=3
"""

from __future__ import annotations

import hashlib
import heapq
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from operator import itemgetter
from pathlib import Path
from typing import Any

from config_flags import env_opt_in

# Avoid tokenizer oversubscription when retrieval and embedding run concurrently.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from dotenv import load_dotenv

load_dotenv()

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.tools import tool
from langchain_huggingface import HuggingFaceEmbeddings
from langgraph.checkpoint.memory import InMemorySaver
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rank_bm25 import BM25Okapi


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BOOK_PATH = Path(os.getenv("FRANKENSTEIN_BOOK", "frankenstein.txt"))
DB_PATH = Path(os.getenv("FRANKENSTEIN_DB", "./frankenstein_db"))

EMBED_MODEL = os.getenv("FRANKENSTEIN_EMBED_MODEL", "BAAI/bge-m3")
EMBED_DEVICE = os.getenv("FRANKENSTEIN_EMBED_DEVICE", "cpu")
EMBED_BATCH = max(1, int(os.getenv("FRANKENSTEIN_EMBED_BATCH", "64")))

MODEL = os.getenv("FRANKENSTEIN_MODEL", "anthropic:claude-sonnet-4-6")

CHUNK_SIZE = max(128, int(os.getenv("FRANKENSTEIN_CHUNK_SIZE", "900")))
CHUNK_OVERLAP = max(0, int(os.getenv("FRANKENSTEIN_CHUNK_OVERLAP", "120")))
if CHUNK_OVERLAP >= CHUNK_SIZE:
    raise ValueError("FRANKENSTEIN_CHUNK_OVERLAP must be smaller than CHUNK_SIZE")

TOP_K = max(1, int(os.getenv("FRANKENSTEIN_TOP_K", "6")))
DENSE_K = max(TOP_K, int(os.getenv("FRANKENSTEIN_DENSE_K", str(max(TOP_K * 2, 12))))
)
BM25_K = max(TOP_K, int(os.getenv("FRANKENSTEIN_BM25_K", str(max(TOP_K * 2, 12))))
)
RRF_K = max(1, int(os.getenv("FRANKENSTEIN_RRF_K", "60")))
RERANK_K = max(TOP_K, int(os.getenv("FRANKENSTEIN_RERANK_K", str(max(TOP_K * 2, 12)))))

ENABLE_WEB = env_opt_in("FRANKENSTEIN_WEB_SEARCH")
ENABLE_RERANK = env_opt_in("FRANKENSTEIN_RERANK")
RERANK_MODEL = os.getenv(
    "FRANKENSTEIN_RERANK_MODEL",
    "BAAI/bge-reranker-v2-m3",
)

CACHE_SIZE = max(0, int(os.getenv("FRANKENSTEIN_CACHE_SIZE", "128")))
WEB_CACHE_SIZE = max(0, int(os.getenv("FRANKENSTEIN_WEB_CACHE_SIZE", "64")))
WEB_RESULTS = max(1, int(os.getenv("FRANKENSTEIN_WEB_RESULTS", "3")))

COLLECTION_NAME = "frankenstein"
METADATA_FILE = "index_metadata.json"

# A small pool is enough: dense embedding calls are normally the expensive
# operation; BM25 itself is CPU-cheap. Two workers avoid oversubscription.
SEARCH_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rag")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

TOKEN_RE = re.compile(r"[a-z0-9]+")


def normalize(text: str) -> list[str]:
    """Cheap, deterministic tokenizer for BM25."""
    return TOKEN_RE.findall(text.lower())


def clean_book_text(text: str) -> str:
    """Remove common Project Gutenberg boilerplate while preserving content."""
    start_markers = (
        "*** START OF THE PROJECT GUTENBERG EBOOK",
        "*** START OF THIS PROJECT GUTENBERG EBOOK",
    )
    end_markers = (
        "*** END OF THE PROJECT GUTENBERG EBOOK",
        "*** END OF THIS PROJECT GUTENBERG EBOOK",
    )

    start = -1
    for marker in start_markers:
        pos = text.find(marker)
        if pos >= 0:
            start = text.find("\n", pos)
            break

    end = -1
    for marker in end_markers:
        pos = text.find(marker)
        if pos >= 0:
            end = pos
            break

    if start >= 0:
        text = text[start + 1 :]
    if end >= 0:
        text = text[:end]

    return text.strip()


def corpus_fingerprint(text: str) -> str:
    """Fingerprint content and every setting that changes the index."""
    payload = "\x1f".join(
        (
            text,
            str(CHUNK_SIZE),
            str(CHUNK_OVERLAP),
            EMBED_MODEL,
            str(EMBED_DEVICE),
            COLLECTION_NAME,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def stable_id(chunk_index: int, content: str) -> str:
    return hashlib.sha1(f"{chunk_index}\x1f{content}".encode("utf-8")).hexdigest()


def read_metadata(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def write_metadata(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class SearchHit:
    document: Document
    score: float


class KnowledgeBase:
    def __init__(self) -> None:
        if not BOOK_PATH.exists():
            raise FileNotFoundError(
                f"Missing {BOOK_PATH}. Put Frankenstein.txt beside this script "
                "or set FRANKENSTEIN_BOOK."
            )

        self.text = clean_book_text(
            BOOK_PATH.read_text(encoding="utf-8", errors="replace")
        )
        if not self.text:
            raise ValueError("Frankenstein text file is empty.")

        self.fingerprint = corpus_fingerprint(self.text)
        self.metadata_path = DB_PATH / METADATA_FILE

        # Embedding configuration is explicit so CPU/GPU deployments can tune
        # throughput without changing application code.
        self.embeddings = HuggingFaceEmbeddings(
            model_name=EMBED_MODEL,
            model_kwargs={"device": EMBED_DEVICE},
            encode_kwargs={
                "normalize_embeddings": True,
                "batch_size": EMBED_BATCH,
            },
        )

        self.documents = self._load_or_split_documents()
        self.vectorstore = self._load_or_build_chroma()

        # BM25 tokenization is done exactly once at startup.
        self._bm25_tokens = [normalize(d.page_content) for d in self.documents]
        self.bm25 = BM25Okapi(self._bm25_tokens)

        # CrossEncoder is intentionally lazy: disabled by default and not
        # loaded until the first query when enabled.
        self._reranker = None

        # Per-instance retrieval cache avoids repeated embedding + BM25 work.
        if CACHE_SIZE:
            self._cached_format_results = lru_cache(maxsize=CACHE_SIZE)(
                self._format_results_uncached
            )
        else:
            self._cached_format_results = self._format_results_uncached

    def _load_or_split_documents(self) -> list[Document]:
        metadata = read_metadata(self.metadata_path)

        # If the persisted metadata matches, splitting is deterministic and
        # cheap; no need to deserialize a second document store.
        if metadata and (
            metadata.get("fingerprint") == self.fingerprint
            and metadata.get("chunk_size") == CHUNK_SIZE
            and metadata.get("chunk_overlap") == CHUNK_OVERLAP
        ):
            expected = int(metadata.get("documents", 0))
        else:
            expected = 0

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        chunks = splitter.split_text(self.text)

        if expected and expected != len(chunks):
            # Content/config fingerprint says the source is current but the
            # metadata is inconsistent. Recompute rather than trusting it.
            expected = 0

        documents = [
            Document(
                page_content=chunk,
                metadata={
                    "source": str(BOOK_PATH),
                    "chunk": i,
                    "corpus_fingerprint": self.fingerprint,
                    "id": stable_id(i, chunk),
                },
            )
            for i, chunk in enumerate(chunks)
        ]
        return documents

    def _new_vectorstore(self) -> Chroma:
        return Chroma(
            collection_name=COLLECTION_NAME,
            persist_directory=str(DB_PATH),
            embedding_function=self.embeddings,
        )

    def _index_is_reusable(self, metadata: dict[str, Any] | None) -> bool:
        if not metadata:
            return False
        return (
            metadata.get("fingerprint") == self.fingerprint
            and metadata.get("embedding_model") == EMBED_MODEL
            and metadata.get("embedding_device") == EMBED_DEVICE
            and metadata.get("chunk_size") == CHUNK_SIZE
            and metadata.get("chunk_overlap") == CHUNK_OVERLAP
            and metadata.get("documents") == len(self.documents)
        )

    def _load_or_build_chroma(self) -> Chroma:
        DB_PATH.mkdir(parents=True, exist_ok=True)
        metadata = read_metadata(self.metadata_path)

        if self._index_is_reusable(metadata):
            print("Loading persistent Chroma index...")
            try:
                store = self._new_vectorstore()
                # Count is a cheap integrity check and catches empty/stale DBs.
                if store._collection.count() == len(self.documents):
                    return store
            except Exception as exc:
                print(f"Persisted index unavailable; rebuilding: {exc}")

        print(f"Building index: {len(self.documents)} chunks...")

        # Remove stale vectors before recreating the collection.
        try:
            stale = self._new_vectorstore()
            stale.delete_collection()
        except Exception:
            pass

        store = self._new_vectorstore()

        batch_size = max(1, min(256, EMBED_BATCH * 2))
        ids = [d.metadata["id"] for d in self.documents]

        for start in range(0, len(self.documents), batch_size):
            end = min(start + batch_size, len(self.documents))
            store.add_documents(
                self.documents[start:end],
                ids=ids[start:end],
            )
            print(f"Indexed {end}/{len(self.documents)}")

        write_metadata(
            self.metadata_path,
            {
                "fingerprint": self.fingerprint,
                "embedding_model": EMBED_MODEL,
                "embedding_device": EMBED_DEVICE,
                "chunk_size": CHUNK_SIZE,
                "chunk_overlap": CHUNK_OVERLAP,
                "documents": len(self.documents),
            },
        )
        return store

    def dense_search(self, query: str) -> list[SearchHit]:
        docs = self.vectorstore.similarity_search_with_score(query, k=DENSE_K)
        return [SearchHit(doc, float(score)) for doc, score in docs]

    def lexical_search(self, query: str) -> list[SearchHit]:
        scores = self.bm25.get_scores(normalize(query))

        # heapq.nlargest avoids sorting the entire corpus when only BM25_K
        # candidates are needed.
        ranked = heapq.nlargest(
            BM25_K,
            enumerate(scores),
            key=itemgetter(1),
        )
        return [
            SearchHit(self.documents[i], float(score))
            for i, score in ranked
        ]

    def hybrid_search(self, query: str) -> list[Document]:
        # Dense retrieval and BM25 are independent.
        dense_future = SEARCH_POOL.submit(self.dense_search, query)
        lexical_future = SEARCH_POOL.submit(self.lexical_search, query)

        dense = dense_future.result()
        lexical = lexical_future.result()

        # RRF keyed by deterministic chunk ID rather than full text.
        scores: dict[str, float] = {}
        docs: dict[str, Document] = {}

        for rank, hit in enumerate(dense, start=1):
            key = hit.document.metadata["id"]
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
            docs[key] = hit.document

        for rank, hit in enumerate(lexical, start=1):
            key = hit.document.metadata["id"]
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
            docs[key] = hit.document

        candidate_count = RERANK_K if ENABLE_RERANK else TOP_K
        ranked_ids = heapq.nlargest(
            min(candidate_count, len(scores)),
            scores,
            key=scores.get,
        )
        selected = [docs[key] for key in ranked_ids]

        reranker = self._get_reranker()
        if reranker and selected:
            pairs = [(query, d.page_content) for d in selected]
            rerank_scores = reranker.predict(pairs, show_progress_bar=False)
            selected = [
                doc
                for _, doc in heapq.nlargest(
                    TOP_K,
                    zip(rerank_scores, selected),
                    key=itemgetter(0),
                )
            ]

        return selected[:TOP_K]

    def _get_reranker(self):
        if not ENABLE_RERANK:
            return None
        if self._reranker is None:
            from sentence_transformers import CrossEncoder

            self._reranker = CrossEncoder(
                RERANK_MODEL,
                device=EMBED_DEVICE,
            )
        return self._reranker

    def _format_results_uncached(self, query: str) -> str:
        docs = self.hybrid_search(query)
        if not docs:
            return "No relevant passages found."

        # Keep tool output compact to reduce downstream LLM token cost.
        return "\n\n".join(
            f"[Frankenstein chunk {doc.metadata.get('chunk', '?')}]\n"
            f"{doc.page_content}"
            for doc in docs
        )

    def format_results(self, query: str) -> str:
        query = query.strip()
        if not query:
            return "No query provided."
        return self._cached_format_results(query)

    def stats(self) -> dict[str, Any]:
        return {
            "book": str(BOOK_PATH),
            "chunks": len(self.documents),
            "embedding_model": EMBED_MODEL,
            "embedding_device": EMBED_DEVICE,
            "embedding_batch": EMBED_BATCH,
            "agent_model": MODEL,
            "dense_k": DENSE_K,
            "bm25_k": BM25_K,
            "final_k": TOP_K,
            "rerank_k": RERANK_K if ENABLE_RERANK else None,
            "reranker": RERANK_MODEL if ENABLE_RERANK else None,
            "web_search": ENABLE_WEB,
            "database": str(DB_PATH),
            "cache_size": CACHE_SIZE,
        }


# ---------------------------------------------------------------------------
# Agent tools
# ---------------------------------------------------------------------------

KB: KnowledgeBase | None = None


@tool
def search_book(query: str) -> str:
    """Search Mary Shelley's Frankenstein using hybrid semantic + lexical retrieval."""
    if KB is None:
        return "Knowledge base is not initialized."
    return KB.format_results(query)


@tool
def web_search(query: str) -> str:
    """Search the live web for criticism, historical context, or modern interpretations."""
    if not ENABLE_WEB:
        return "Web search is disabled."

    query = query.strip()
    if not query:
        return "No web query provided."

    # A trusted external operator must provision the exact signed grant.
    # The agent cannot issue grants; missing/invalid grants deny execution.
    from authority import ControlPlane, ScopeContract, AuthorityError
    key_hex = os.getenv("SENTINEL_AUTHORITY_KEY_HEX", "")
    grant_path = os.getenv("SENTINEL_WEB_GRANT_FILE", "")
    if not key_hex or not grant_path:
        return "DENIED: external web-search authorization missing"
    try:
        key = bytes.fromhex(key_hex)
        grant = json.loads(Path(grant_path).read_text(encoding="utf-8"))
        control = ControlPlane(key, os.getenv("SENTINEL_AUTHORITY_DB", "./authority.sqlite3"), ScopeContract(frozenset({"web_search"}), os.getenv("SENTINEL_TENANT", "local")))
        try:
            try:
                return control.execute(grant, control.scope.tenant, "web_search", {"query": query}, _web_search_uncached)
            except AuthorityError:
                raise
            except Exception as exc:
                return f"Web search failed (outcome UNKNOWN): {type(exc).__name__}"
        finally:
            control.close()
    except (AuthorityError, ValueError, OSError, json.JSONDecodeError) as exc:
        return f"DENIED: {type(exc).__name__}"


def _web_search_uncached(query: str) -> str:
    from ddgs import DDGS

    results = DDGS().text(query, max_results=WEB_RESULTS)
    if not results:
        return "No web results found."

    lines: list[str] = []
    for item in results:
        title = item.get("title", "")
        body = item.get("body", "")
        href = item.get("href", "")
        lines.append(f"{title}\n{body}\n{href}")
    return "\n\n".join(lines)


if WEB_CACHE_SIZE:
    _web_search_cached = lru_cache(maxsize=WEB_CACHE_SIZE)(_web_search_uncached)
else:
    _web_search_cached = _web_search_uncached


SYSTEM_PROMPT = """You are a rigorous literary scholar specializing in Mary Shelley's Frankenstein.

Rules:
1. For questions about events, characters, passages, chronology, quotations,
   or details of the novel, use search_book first.
2. Never invent a quotation. If exact wording matters, retrieve the passage.
3. Distinguish textual evidence from interpretation.
4. Use web_search only for external criticism, historical context, or modern
   interpretations.
5. When citing the novel, identify the retrieved chunk number when useful.
6. Keep answers precise. Do not dump retrieved passages unless the user asks.
7. If the evidence is insufficient, say so instead of hallucinating.
"""


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class FrankensteinAgent:
    def __init__(self) -> None:
        global KB

        print("Initializing knowledge base...")
        KB = KnowledgeBase()

        print(f"Model: {MODEL}")
        print(f"Embedding: {EMBED_MODEL} [{EMBED_DEVICE}, batch={EMBED_BATCH}]")
        print(f"Chunks: {len(KB.documents)}")
        print(
            f"Hybrid retrieval: dense={DENSE_K}, "
            f"BM25={BM25_K}, final={TOP_K}, "
            f"rerank={'on' if ENABLE_RERANK else 'off'}"
        )

        self.checkpointer = InMemorySaver()
        self.model = init_chat_model(MODEL, temperature=0.2)

        self.agent = create_agent(
            model=self.model,
            tools=[search_book, web_search],
            system_prompt=SYSTEM_PROMPT,
            checkpointer=self.checkpointer,
        )

    def ask(self, question: str, thread_id: str = "default") -> str:
        result = self.agent.invoke(
            {"messages": [{"role": "user", "content": question}]},
            config={"configurable": {"thread_id": thread_id}},
        )

        messages = result.get("messages", [])
        for message in reversed(messages):
            if getattr(message, "type", None) == "ai":
                content = getattr(message, "content", "")
                if isinstance(content, str):
                    return content
                return str(content)

        return "No response generated."

    @staticmethod
    def reset(thread_id: str = "default") -> str:
        # InMemorySaver has no portable cross-version delete API.
        # The CLI creates a fresh thread ID, which is reliable.
        return f"Conversation reset. Thread: {thread_id}"

    def stats(self) -> dict[str, Any]:
        return KB.stats() if KB is not None else {}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    try:
        agent = FrankensteinAgent()
    except Exception as exc:
        print(f"\nStartup error: {exc}", file=sys.stderr)
        return 1

    print("\n=== Frankenstein Agent ===")
    print("Commands: /stats  /reset  /quit")
    print("Ask questions about the novel.\n")

    thread_id = "cli"

    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            SEARCH_POOL.shutdown(wait=False, cancel_futures=True)
            return 0

        if not question:
            continue

        command = question.lower()

        if command in {"/quit", "/exit", "quit", "exit", "bye"}:
            print("Goodbye.")
            SEARCH_POOL.shutdown(wait=False, cancel_futures=True)
            return 0

        if command == "/stats":
            for key, value in agent.stats().items():
                print(f"{key}: {value}")
            print()
            continue

        if command == "/reset":
            thread_id = f"cli-{hashlib.sha1(os.urandom(16)).hexdigest()[:10]}"
            print("Conversation reset.\n")
            continue

        try:
            answer = agent.ask(question, thread_id=thread_id)
            print(f"\nAgent: {answer}\n")
        except Exception as exc:
            print(f"\nRequest error: {exc}\n", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
