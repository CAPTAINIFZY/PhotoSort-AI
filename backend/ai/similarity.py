"""
ai/similarity.py — Photo deduplication via cosine-similarity clustering.

Algorithm
---------
1. Build a pairwise cosine-similarity matrix (batch dot-product of
   normalised embeddings — O(N²) in memory but fast with numpy).
2. Connect any pair with similarity ≥ threshold as an edge in a graph.
3. Find connected components via union-find (no external graph library
   needed; avoids adding networkx as a dependency).
4. Assign cluster IDs only to photos that share at least one match.
   Solo photos (no match above threshold) get no entry in the output.

Complexity: O(N²) pairwise similarity + O(N·α(N)) union-find.
For N=300 this is ~90 K dot-products — trivially fast on CPU numpy.

pick_cluster_representative
---------------------------
Chooses the photo with the highest sharpness_score as the placeholder
"AI Pick" for each cluster.  Phase 5 will replace this with a proper
weighted composite score.
"""

from __future__ import annotations

import numpy as np


# ── Union-Find ────────────────────────────────────────────────────────────────

class _UF:
    """Path-compressing, rank-union find."""

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.rank   = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]   # path halving
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


# ── Public API ────────────────────────────────────────────────────────────────

def cluster_photos(
    embeddings: dict[str, np.ndarray],
    threshold: float = 0.92,
) -> dict[str, int]:
    """
    Group photos with pairwise cosine similarity ≥ threshold.

    Parameters
    ----------
    embeddings : dict  photo_id → np.ndarray (512,) L2-normalised
    threshold  : float cosine similarity cutoff (default 0.92)

    Returns
    -------
    dict  photo_id → cluster_id (int, 0-indexed)
    Only photos that have at least one match appear in the output.
    Photos with no match above threshold are excluded (they get
    similarity_group=NULL in the DB, not a solo cluster of size 1).

    Edge cases handled
    ------------------
    - Empty input          → {}
    - No pairs ≥ threshold → {}  (all singles)
    - One giant cluster    → all IDs map to cluster_id=0
    """
    if not embeddings:
        return {}

    ids = list(embeddings.keys())
    n   = len(ids)

    if n == 1:
        return {}

    # Stack into (N, D) matrix — all embeddings must be L2-normalised
    mat = np.stack([embeddings[pid] for pid in ids], axis=0)  # (N, 512)

    # Pairwise cosine similarity: sim[i,j] = mat[i] · mat[j]
    sim = mat @ mat.T                                          # (N, N)

    # Build union-find over pairs above threshold (upper triangle only)
    uf = _UF(n)
    rows, cols = np.where(np.triu(sim, k=1) >= threshold)
    for r, c in zip(rows.tolist(), cols.tolist()):
        uf.union(int(r), int(c))

    # Find roots for every node
    roots = [uf.find(i) for i in range(n)]

    # Identify roots that represent multi-member components
    from collections import Counter
    root_counts = Counter(roots)
    multi_roots = {r for r, cnt in root_counts.items() if cnt >= 2}

    if not multi_roots:
        return {}

    # Assign sequential cluster IDs to multi-member roots
    root_to_cid: dict[int, int] = {}
    for root in sorted(multi_roots):
        root_to_cid[root] = len(root_to_cid)

    return {
        ids[i]: root_to_cid[roots[i]]
        for i in range(n)
        if roots[i] in root_to_cid
    }


def pick_cluster_representative(
    photo_ids: list[str],
    sharpness_scores: dict[str, float | None],
) -> str:
    """
    Return the photo_id with the highest sharpness_score in the cluster.

    Falls back to the first photo_id if no sharpness scores are available
    (e.g. all failed during analysis).
    """
    if not photo_ids:
        raise ValueError("photo_ids must not be empty")

    def _score(pid: str) -> float:
        val = sharpness_scores.get(pid)
        return float(val) if val is not None else -1.0

    return max(photo_ids, key=_score)
