"""
Lightweight embedding service for semantic similarity matching.
Uses paraphrase-multilingual-MiniLM-L12-v2 (~470MB, supports Chinese).
Singleton pattern: model loads once on first use, then cached globally.
"""

import re
import numpy as np
from typing import Optional

_model = None
_model_loading = False


def _get_model():
    """Lazy-load the sentence-transformers model (singleton)."""
    global _model, _model_loading
    if _model is not None:
        return _model
    if _model_loading:
        return None
    _model_loading = True
    try:
        from sentence_transformers import SentenceTransformer

        print("[EmbeddingService] Loading paraphrase-multilingual-MiniLM-L12-v2 ...")
        _model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        print("[EmbeddingService] Model loaded successfully.")
        return _model
    except Exception as e:
        print(f"[EmbeddingService] Failed to load model: {e}")
        _model_loading = False
        return None


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _split_query_clauses(query: str) -> list[str]:
    """Split Chinese query into meaningful sub-clauses by punctuation."""
    # Split by Chinese/English punctuation
    clauses = re.split(r"[，。、；！？\n]+", query)
    # Filter out very short fragments
    return [c.strip() for c in clauses if len(c.strip()) >= 4]


def compute_semantic_coverage(
    query: str,
    summary: str,
    threshold: float = 0.35,
) -> Optional[dict]:
    """
    Compute semantic coverage of query sub-clauses against rolling_summary.

    Returns:
        {
            "coverage_pct": float,       # 0.0 ~ 1.0
            "coverage_label": str,       # "高" / "中" / "低"
            "uncovered_clauses": list,   # clauses not yet answered
            "clause_scores": list,       # [(clause, score), ...]
        }
        Returns None if model is unavailable.
    """
    model = _get_model()
    if model is None:
        return None

    if not query or not summary:
        return None

    clauses = _split_query_clauses(query)
    if not clauses:
        return None

    try:
        # Encode all clauses + summary in one batch
        texts = clauses + [summary]
        embeddings = model.encode(texts, normalize_embeddings=True)

        summary_emb = embeddings[-1]
        clause_embs = embeddings[:-1]

        # Compute similarity for each clause
        clause_scores = []
        covered_count = 0
        uncovered = []
        for i, clause in enumerate(clauses):
            sim = _cosine_sim(clause_embs[i], summary_emb)
            clause_scores.append((clause, round(sim, 3)))
            if sim >= threshold:
                covered_count += 1
            else:
                uncovered.append(clause)

        cov_pct = covered_count / len(clauses) if clauses else 0.0
        cov_label = "高" if cov_pct >= 0.7 else ("中" if cov_pct >= 0.4 else "低")

        return {
            "coverage_pct": cov_pct,
            "coverage_label": cov_label,
            "uncovered_clauses": uncovered,
            "clause_scores": clause_scores,
        }
    except Exception as e:
        print(f"[EmbeddingService] compute_semantic_coverage error: {e}")
        return None


def compute_hybrid_coverage(
    intents: list,
    summary: str,
    scene_queue: list = None,
    threshold: float = 0.35,
    semantic_weight: float = 0.4,
    scene_weight: float = 0.6,
) -> Optional[dict]:
    """
    混合覆蓋率: 結合語義覆蓋 + 場景完成率。

    Args:
        intents: LLM 分解的用戶意圖清單 (取代子句切分)
        summary: rolling_summary 文本
        scene_queue: SceneItem list (有 status 屬性)
        threshold: Embedding 相似度閾值
        semantic_weight: 語義覆蓋的權重 (default 0.4)
        scene_weight: 場景完成的權重 (default 0.6)

    Returns:
        {
            "coverage_pct": float,          # 最終混合覆蓋率
            "coverage_label": str,          # 高/中/低
            "semantic_pct": float,          # 語義覆蓋率
            "scene_pct": float,             # 場景完成率
            "uncovered_intents": list,      # 未被語義覆蓋的意圖
            "uncovered_scenes": list,       # 未完成的場景 label
            "intent_scores": list,          # [(intent, score), ...]
        }
    """
    if not intents:
        return None

    # --- Part 1: Semantic Coverage (intents vs summary) ---
    semantic_pct = 0.0
    uncovered_intents = list(intents)
    intent_scores = []

    model = _get_model()
    if model is not None and summary:
        try:
            texts = list(intents) + [summary]
            embeddings = model.encode(texts, normalize_embeddings=True)
            summary_emb = embeddings[-1]
            intent_embs = embeddings[:-1]

            covered_count = 0
            uncovered_intents = []
            for i, intent in enumerate(intents):
                sim = _cosine_sim(intent_embs[i], summary_emb)
                intent_scores.append((intent, round(sim, 3)))
                if sim >= threshold:
                    covered_count += 1
                else:
                    uncovered_intents.append(intent)

            semantic_pct = covered_count / len(intents) if intents else 0.0
        except Exception as e:
            print(f"[HybridCoverage] Semantic calculation error: {e}")
            semantic_pct = 0.0
            uncovered_intents = list(intents)

    # --- Part 2: Scene Completion Rate ---
    scene_pct = 0.0
    uncovered_scenes = []
    has_scenes = False

    if scene_queue:
        has_scenes = True
        total = len(scene_queue)
        completed = 0
        for s in scene_queue:
            status = getattr(s, "status", None) or (
                s.get("status") if isinstance(s, dict) else None
            )
            label = getattr(s, "label", None) or (
                s.get("label", "?") if isinstance(s, dict) else "?"
            )
            turns = getattr(s, "turns_spent", 0) or (
                s.get("turns_spent", 0) if isinstance(s, dict) else 0
            )
            if status == "COMPLETED":
                completed += 1
            elif status == "ACTIVE" or turns > 0:
                # ACTIVE 或已花過 Turn 的場景 = 正在處理中，不算 uncovered
                completed += 0.5
            else:
                # PENDING 且 turns_spent=0 才是真正尚未分析的缺口
                uncovered_scenes.append(label)
        scene_pct = completed / total if total > 0 else 0.0

    # --- Part 3: Blended Coverage ---
    if has_scenes:
        coverage_pct = semantic_weight * semantic_pct + scene_weight * scene_pct
    else:
        # 無場景時: 純語義覆蓋
        coverage_pct = semantic_pct

    # Label
    if coverage_pct >= 0.7:
        coverage_label = "高"
    elif coverage_pct >= 0.4:
        coverage_label = "中"
    else:
        coverage_label = "低"

    return {
        "coverage_pct": coverage_pct,
        "coverage_label": coverage_label,
        "semantic_pct": semantic_pct,
        "scene_pct": scene_pct,
        "uncovered_intents": uncovered_intents,
        "uncovered_scenes": uncovered_scenes,
        "intent_scores": intent_scores,
    }
