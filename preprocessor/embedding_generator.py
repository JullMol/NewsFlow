import numpy as np
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import EMBEDDING_MODEL, EMBEDDING_DIM, BATCH_SIZE

class EmbeddingGenerator:
    def __init__(self, model_name: str = EMBEDDING_MODEL):
        print(f"[EMBEDDING] Loading model: {model_name}")
        self.model = SentenceTransformer(model_name)
        self.dim = EMBEDDING_DIM
        print(f"  Model loaded! Output dimension: {self.dim}")

    def generate(self, text: str) -> list[float]:
        embedding = self.model.encode(text, show_progress_bar=False)
        return embedding.tolist()

    def generate_batch(self, texts: list[str], batch_size: int = BATCH_SIZE) -> list[list[float]]:
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=True,
            normalize_embeddings=True,
        )
        return embeddings.tolist()


def generate_article_embeddings(
    articles: list[dict],
    generator: EmbeddingGenerator = None,
) -> list[dict]:
    if generator is None:
        generator = EmbeddingGenerator()

    texts = []
    for article in articles:
        title = article.get("title", "")
        content = article.get("content", "")[:512]
        combined = f"{title}. {content}" if title else content
        texts.append(combined)

    print(f"[EMBEDDING] Generating embeddings for {len(texts)} articles")
    embeddings = generator.generate_batch(texts)

    for article, embedding in zip(articles, embeddings):
        article["embedding"] = embedding

    return articles


_generator_instance = None

def get_generator() -> EmbeddingGenerator:
    global _generator_instance
    if _generator_instance is None:
        _generator_instance = EmbeddingGenerator()
    return _generator_instance


if __name__ == "__main__":
    gen = EmbeddingGenerator()

    test_texts = [
        "Presiden meresmikan jembatan baru di Kalimantan",
        "Pembangunan infrastruktur jembatan di Borneo diresmikan",
        "Harga saham teknologi melonjak tajam hari ini",
    ]

    embeddings = gen.generate_batch(test_texts)
    print(f"Embedding shape: {len(embeddings)} x {len(embeddings[0])}")

    # Test similarity
    from numpy import dot
    from numpy.linalg import norm

    for i in range(len(test_texts)):
        for j in range(i + 1, len(test_texts)):
            a, b = np.array(embeddings[i]), np.array(embeddings[j])
            sim = dot(a, b) / (norm(a) * norm(b))
            print(f"Similarity [{i}] vs [{j}]: {sim:.4f}")
            print(f"  '{test_texts[i][:50]}'")
            print(f"  '{test_texts[j][:50]}'")