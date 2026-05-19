from __future__ import annotations

import logging
import math
from functools import lru_cache

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from .config import get_settings
from .validation import validate_embedding_vector


logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def load_embedding_model() -> SentenceTransformer:
    settings = get_settings()
    device = "cuda" if settings.use_cuda and torch.cuda.is_available() else "cpu"
    model = SentenceTransformer(settings.embedding_model, device=device)
    if device == "cuda":
        try:
            model.half()
        except Exception as exc:
            logger.warning("Could not switch embedding model to fp16 safely: %s", exc)
    return model


def embed_texts(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    if not texts:
        return []
    model = load_embedding_model()
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=True,
    )
    vectors = np.asarray(embeddings, dtype=np.float32)
    output = vectors.tolist()
    for vector in output:
        validate_embedding_vector(vector, dimensions=1024, norm_tolerance=0.01)
    return output


def embed_one(text: str) -> list[float]:
    vectors = embed_texts([text], batch_size=1)
    return vectors[0]


def estimate_vector_memory(num_vectors: int, dimensions: int = 1024) -> dict:
    raw_float32_bytes = int(num_vectors) * int(dimensions) * 4
    return {
        "num_vectors": int(num_vectors),
        "dimensions": int(dimensions),
        "raw_float32_bytes": raw_float32_bytes,
        "raw_float32_mb": round(raw_float32_bytes / (1024 * 1024), 3),
        "list_float_note": "MongoDB list floats have BSON overhead beyond raw float32 memory.",
        "norm_expected": 1.0,
        "cosine_ready": True,
    }

