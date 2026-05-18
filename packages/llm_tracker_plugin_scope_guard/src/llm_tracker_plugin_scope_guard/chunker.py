"""Semantic boundary detection for ``scope_documents`` (ADR-0030 §D5).

CP3 implementation. Pins ADR-0030 §Q1 — the rolling-mean drop threshold and
window size — to the constants below.

Pipeline:

1. ``_segment_sentences`` — paragraph-split on blank lines, then sentence-split
   on terminal punctuation followed by whitespace and a capital / CJK / quote
   opener. Library swap to ``blingfire`` or ``pysbd`` is queued under
   ADR-0030 §Deferred §6 if quality is insufficient.
2. The caller-injected ``embed(text)`` callable embeds each sentence. Tests
   stub this; CP4 wires it to the real OpenAI ``EmbeddingClient``.
3. ``_detect_boundaries`` walks adjacent-sentence cosine similarities and
   flags a chunk boundary where similarity drops below
   ``rolling_mean - DROP_THRESHOLD`` over the previous ``WINDOW`` similarities.
4. ``_enforce_size_bounds`` applies the min-50 / max-500 token bounds from
   ADR-0030 §D5 §4 (whitespace-word approximation — see ``_token_count``).
5. Each resulting chunk is re-embedded so the returned vector matches the
   chunk's final content (the same string later written to
   ``scope_chunks.content``).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import NamedTuple

import numpy as np

# ADR-0030 §D5 §1 - sentence segmenter. Split on terminal punctuation
# (Latin or CJK fullwidth), then whitespace, then a Latin capital, an opening
# quote / paren, or a CJK character. The CJK ranges cover Hangul
# (U+AC00..U+D7AF) and CJK Unified Ideographs (U+4E00..U+9FFF) so Korean /
# Japanese / Chinese scope documents segment without a separate code path.
_SENTENCE_RE = re.compile(
    # terminal punctuation: . ? ! plus CJK fullwidth period / ? / !
    # (U+3002, U+FF1F, U+FF01). Ambiguous-glyph lint suppressed: pattern intent.
    "(?<=[.?!。？！])"  # noqa: RUF001
    "\\s+"
    # next-sentence opener: latin capital, ASCII double-quote / paren,
    # curly left double / single quote (U+201C / U+2018), or any CJK
    # ideograph (U+4E00..U+9FFF) / Hangul syllable (U+AC00..U+D7AF).
    '(?=[A-Z"(“‘]|[一-鿿가-힯])'  # noqa: RUF001
)
_PARAGRAPH_RE = re.compile(r"\n{2,}")

# ADR-0030 §Q1 — pinned at CP3. A boundary is inserted at sentence ``i + 1``
# when the cosine similarity between sentences ``i`` and ``i + 1`` drops
# below the mean of the previous ``_BOUNDARY_WINDOW`` adjacent similarities,
# minus ``_BOUNDARY_DROP_THRESHOLD``.
#
# Benchmark (``tests/test_chunker.py::test_q1_*``):
#
# - ``window=3, drop=0.15``  → chosen. Recovers all expected boundaries on
#   the 3-topic fixture; does not over-split on a smooth-prose fixture with
#   a single ~0.16 dip.
# - ``window=3, drop=0.10``  → over-splits. The single dip in the
#   smooth-prose fixture triggers a false boundary.
# - ``window=5, drop=0.15``  → under-splits short documents. The five-sim
#   warm-up swallows the first topic shift in a 15-sentence corpus.
_BOUNDARY_WINDOW = 3
_BOUNDARY_DROP_THRESHOLD = 0.15

# ADR-0030 §D5 §4 — chunk size bounds. Token count is approximated by
# whitespace-split word count: cheap, predictable, and avoids pulling
# ``tiktoken`` as a dependency. For English text the
# token : word ratio runs about 1.3 : 1 so 50 words ≈ 65 tokens and
# 500 words ≈ 650 tokens — both inside the band the ADR meant to
# express (chunks readable in isolation, well below the 8191-token
# embedding-input ceiling).
_MIN_TOKENS = 50
_MAX_TOKENS = 500


class ChunkRecord(NamedTuple):
    """One row's worth of ``scope_chunks`` content (CP5 writes the DB)."""

    chunk_index: int
    content: str
    embedding: list[float]


def _segment_sentences(text: str) -> list[str]:
    """Paragraph-split, then sentence-split. Returns trimmed non-empty parts."""
    stripped = text.strip()
    if not stripped:
        return []
    sentences: list[str] = []
    for paragraph in _PARAGRAPH_RE.split(stripped):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        for part in _SENTENCE_RE.split(paragraph):
            part = part.strip()
            if part:
                sentences.append(part)
    return sentences


def _token_count(text: str) -> int:
    return len(text.split())


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _detect_boundaries(
    similarities: list[float],
    *,
    window: int = _BOUNDARY_WINDOW,
    drop: float = _BOUNDARY_DROP_THRESHOLD,
) -> list[int]:
    """Sentence indices that *start* a new chunk (the index 0 is implicit).

    ``similarities[i]`` is cosine(sentences[i], sentences[i+1]). A boundary
    lands at sentence ``i + 1`` when ``similarities[i]`` falls strictly
    below ``rolling_mean - drop``. The first ``window`` similarities warm
    up the baseline and cannot themselves trigger a boundary.
    """
    if len(similarities) <= window:
        return []
    boundaries: list[int] = []
    for i in range(window, len(similarities)):
        baseline = sum(similarities[i - window : i]) / window
        if similarities[i] < baseline - drop:
            boundaries.append(i + 1)
    return boundaries


def _group_into_chunks(sentence_count: int, boundaries: list[int]) -> list[list[int]]:
    if sentence_count == 0:
        return []
    cut = sorted(set(boundaries))
    groups: list[list[int]] = []
    start = 0
    for b in cut:
        if b <= start or b >= sentence_count:
            continue
        groups.append(list(range(start, b)))
        start = b
    groups.append(list(range(start, sentence_count)))
    return groups


def _enforce_size_bounds(
    groups: list[list[int]],
    sentences: list[str],
    similarities: list[float],
) -> list[list[int]]:
    """Merge below-min, split above-max (ADR-0030 §D5 §4)."""
    # Pass 1 — merge below-min into the next neighbour; if last, into the
    # previous accepted group; if there is no neighbour at all, accept as-is.
    merged: list[list[int]] = []
    pending: list[list[int]] = list(groups)
    i = 0
    while i < len(pending):
        g = pending[i]
        words = _token_count(" ".join(sentences[s] for s in g))
        if words < _MIN_TOKENS:
            if i + 1 < len(pending):
                pending[i + 1] = g + pending[i + 1]
                i += 1
                continue
            if merged:
                merged[-1] = merged[-1] + g
                i += 1
                continue
        merged.append(g)
        i += 1

    # Pass 2 — split above-max on the lowest adjacent similarity inside the
    # group. Re-enqueue halves so the split applies recursively.
    out: list[list[int]] = []
    queue: list[list[int]] = list(merged)
    while queue:
        g = queue.pop(0)
        words = _token_count(" ".join(sentences[s] for s in g))
        if words <= _MAX_TOKENS or len(g) < 2:
            out.append(g)
            continue
        cut = min(range(len(g) - 1), key=lambda k: similarities[g[k]])
        left = g[: cut + 1]
        right = g[cut + 1 :]
        queue.insert(0, right)
        queue.insert(0, left)
    return out


def chunk_document(text: str, embed: Callable[[str], list[float]]) -> list[ChunkRecord]:
    """Chunk ``text`` per ADR-0030 §D5; return one ``ChunkRecord`` per chunk.

    ``embed`` is injected so unit tests stub it; CP4 supplies the real OpenAI
    client. Each chunk's embedding is the embedding of its concatenated
    sentence content — not an average of sentence embeddings — so the stored
    vector exactly represents the string written to ``scope_chunks.content``.
    """
    sentences = _segment_sentences(text)
    if not sentences:
        return []
    if len(sentences) == 1:
        return [ChunkRecord(0, sentences[0], embed(sentences[0]))]

    sent_vecs = [np.asarray(embed(s), dtype=float) for s in sentences]
    similarities = [_cosine(sent_vecs[i], sent_vecs[i + 1]) for i in range(len(sentences) - 1)]
    boundaries = _detect_boundaries(similarities)
    groups = _group_into_chunks(len(sentences), boundaries)
    groups = _enforce_size_bounds(groups, sentences, similarities)

    records: list[ChunkRecord] = []
    for idx, group in enumerate(groups):
        content = " ".join(sentences[s] for s in group)
        records.append(ChunkRecord(idx, content, embed(content)))
    return records
