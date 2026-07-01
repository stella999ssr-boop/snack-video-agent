"""
纯 Python 嵌入函数 — 零 DLL 依赖

使用 sklearn HashingVectorizer（字符级 n-gram）作为占位嵌入。
生产环境替换为中文语义模型（如 DashScope Embedding API 或 text2vec-base-chinese）。

优势：无需 torch/onnxruntime，Windows 免 VC++ 运行时。
劣势：不支持语义相似度，仅基于词汇重叠。
"""

from chromadb.api.types import Documents, Embeddings, EmbeddingFunction
from sklearn.feature_extraction.text import HashingVectorizer


class HashingEmbeddingFunction(EmbeddingFunction):
    """
    基于 HashingVectorizer 的轻量嵌入，符合 ChromaDB EmbeddingFunction 协议。
    """

    def __init__(self, n_features: int = 384):
        self._n_features = n_features
        self._vectorizer = HashingVectorizer(
            n_features=n_features,
            analyzer="char_wb",
            ngram_range=(2, 4),
            alternate_sign=False,
            norm="l2",
        )

    def name(self) -> str:
        return f"hashing-char-wb-{self._n_features}d"

    def __call__(self, input: Documents) -> Embeddings:
        vectors = self._vectorizer.transform(input).toarray()
        return vectors.tolist()
