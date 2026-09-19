"""v4 supplementary framework example. Scripted/hand-designed data; not provider quality. Current verification: validation/report.md."""
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore

class TeachingEmbeddings(Embeddings):
    """Hand-designed vectors demonstrate plumbing, not model quality."""
    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0] if "page" in text.lower() else [0.0, 1.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

store = InMemoryVectorStore(TeachingEmbeddings())
store.add_documents([
    Document(page_content="page offset", metadata={"path": "pagination.py", "tenant": "t1", "revision": "r1"}),
    Document(page_content="page secret", metadata={"path": "private.py", "tenant": "t2", "revision": "r1"}),
    Document(page_content="billing total", metadata={"path": "billing.py", "tenant": "t1", "revision": "r1"}),
], ids=["p1", "s1", "b1"])
hits = store.similarity_search("page", k=1, filter=lambda d: d.metadata["tenant"] == "t1")
print(hits[0].metadata["path"])
print("private_visible=" + str(any(d.metadata["tenant"] != "t1" for d in hits)))
print("embedding_mode=hand_designed_demo")

assert hits[0].metadata["path"] == "pagination.py"
assert all(d.metadata["tenant"] == "t1" for d in hits)
