"""Unit tests for ``llm_tracker_plugin_scope_guard.chunker``.

Pins the semantic-boundary detector's behaviour and documents the
ADR-0030 §Q1 parameter-tuple choice (``window=3``, ``drop=0.15``).

The tests embed via a deterministic vocab-tagged stub. Each "topic" has a
disjoint set of trigger words; cosine within a topic is 1.0 and across
topics is 0.0. This gives the boundary detector clean signals to act on
without making real API calls.
"""

from __future__ import annotations

import numpy as np
import pytest
from llm_tracker_plugin_scope_guard.chunker import (
    _BOUNDARY_DROP_THRESHOLD,
    _BOUNDARY_WINDOW,
    _MAX_TOKENS,
    _MIN_TOKENS,
    ChunkRecord,
    _cosine,
    _detect_boundaries,
    _enforce_size_bounds,
    _segment_sentences,
    chunk_document,
)

_TOPIC_VOCAB: dict[str, tuple[str, ...]] = {
    "weather": ("weather", "rain", "snow", "wind", "cloud", "storm", "sun"),
    "sports": ("sports", "soccer", "football", "tennis", "basketball", "match"),
    "cooking": ("recipe", "cook", "bake", "ingredients", "pasta", "knife"),
}


def _topic_embed(text: str) -> list[float]:
    """Three-dim embedder keyed on disjoint topic vocab."""
    lower = text.lower()
    vec = [0.0, 0.0, 0.0]
    for axis, (topic, words) in enumerate(_TOPIC_VOCAB.items()):
        del topic
        vec[axis] = float(sum(lower.count(w) for w in words))
    if sum(vec) == 0.0:
        return [1e-3, 1e-3, 1e-3]
    return vec


_WEATHER = [
    "Today the weather across the central valley brought heavy rain and steady wind.",
    "Forecast models show the rain band moving east with intermittent wind gusts.",
    "Snow is expected by evening as the storm front pulls cold air south.",
    "Cloud cover thickens overnight, with wind speeds peaking near dawn.",
    "By noon the sun returns and the storm system finally exits the region.",
]
_SPORTS = [
    "Sports analysts reviewed last weekend's soccer match and the tennis quarterfinals.",
    "The football coach signed two new midfielders ahead of the friendly match.",
    "Tennis training resumed this morning despite the wet conditions on the courts.",
    "Basketball drills focused on defensive footwork during the long practice session.",
    "Soccer scouts noted a strong showing from the regional under-21 squad.",
]
_COOKING = [
    "The recipe calls for ingredients you can find at any neighbourhood market today.",
    "First cook the pasta until just tender, then fold it into the warm sauce.",
    "Bake the loaf at moderate heat and rotate it once for an even crust.",
    "Slice the vegetables thinly with a sharp knife and salt them lightly first.",
    "Cook the onions slowly so their sweetness draws out before the other ingredients land.",
]


def _three_topic_text() -> str:
    return " ".join(_WEATHER + _SPORTS + _COOKING)


def test_segment_sentences_simple_punctuation() -> None:
    text = "First sentence. Second sentence! Third one?"
    assert _segment_sentences(text) == [
        "First sentence.",
        "Second sentence!",
        "Third one?",
    ]


def test_segment_sentences_paragraph_break() -> None:
    text = "Heading one\n\nFirst sentence. Second sentence.\n\nLast block."
    assert _segment_sentences(text) == [
        "Heading one",
        "First sentence.",
        "Second sentence.",
        "Last block.",
    ]


def test_segment_sentences_cjk_terminator() -> None:
    text = "한국어 문장입니다. 두번째 문장입니다."
    assert _segment_sentences(text) == [
        "한국어 문장입니다.",
        "두번째 문장입니다.",
    ]


def test_segment_sentences_empty_input() -> None:
    assert _segment_sentences("") == []
    assert _segment_sentences("   \n  \n  ") == []


def test_cosine_orthogonal_zero_and_parallel_one() -> None:
    a = np.array([1.0, 0.0, 0.0])
    b = np.array([0.0, 1.0, 0.0])
    c = np.array([2.0, 0.0, 0.0])
    assert _cosine(a, b) == pytest.approx(0.0)
    assert _cosine(a, c) == pytest.approx(1.0)
    assert _cosine(a, np.zeros(3)) == 0.0


def test_chunk_document_empty_input_returns_empty_list() -> None:
    assert chunk_document("", _topic_embed) == []


def test_chunk_document_single_sentence_returns_single_chunk() -> None:
    records = chunk_document("Only one sentence in this document.", _topic_embed)
    assert len(records) == 1
    assert records[0].chunk_index == 0
    assert records[0].content == "Only one sentence in this document."
    assert len(records[0].embedding) == 3


def test_chunk_document_recovers_three_topic_boundaries() -> None:
    text = _three_topic_text()
    records = chunk_document(text, _topic_embed)
    assert len(records) == 3
    assert [r.chunk_index for r in records] == [0, 1, 2]
    # Each chunk's content should be dominated by one topic.
    contents = [r.content.lower() for r in records]
    assert any("weather" in c or "rain" in c for c in contents[:1])
    assert any("soccer" in c or "tennis" in c for c in contents[1:2])
    assert any("recipe" in c or "pasta" in c for c in contents[2:3])


def test_chunk_document_embedding_is_chunk_content_not_sentence_average() -> None:
    """Each chunk's stored vector must come from re-embedding the chunk string.

    The contract on ``scope_chunks.embedding`` is that it represents the
    chunk's ``content`` column (ADR-0030 §D5 §5). A sentence-average would
    drift from that under the topic-tagged stub embedder.
    """
    text = " ".join(_WEATHER + _SPORTS)
    records = chunk_document(text, _topic_embed)
    for record in records:
        assert record.embedding == _topic_embed(record.content)


def test_detect_boundaries_warmup_window_is_quiet() -> None:
    """The first ``window`` similarities cannot themselves trigger a boundary."""
    sims = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    assert _detect_boundaries(sims) == []


def test_detect_boundaries_short_input_returns_empty() -> None:
    assert _detect_boundaries([]) == []
    assert _detect_boundaries([0.9, 0.1, 0.1]) == []


# --- ADR-0030 §Q1 parameter benchmark ---------------------------------------
#
# Three candidate tuples were evaluated. The chosen one is ``(window=3,
# drop=0.15)`` because it recovers all expected boundaries on a 3-topic
# fixture while staying quiet on a smooth-prose fixture with a single
# mid-text similarity dip.


_THREE_TOPIC_SIMS = (
    [1.0] * 4  # within weather
    + [0.0]  # weather → sports
    + [1.0] * 4  # within sports
    + [0.0]  # sports → cooking
    + [1.0] * 4  # within cooking
)
# Expected boundaries: at sentence 5 (start of sports) and 10 (start of cooking).
_EXPECTED_THREE_TOPIC_BOUNDARIES = [5, 10]

# Smooth prose with one ~0.16 dip but no real topic shift.
_SMOOTH_PROSE_SIMS = [0.95, 0.93, 0.91, 0.78, 0.92, 0.94, 0.92]


def test_q1_chosen_params_recover_three_topic_boundaries() -> None:
    assert _BOUNDARY_WINDOW == 3
    assert pytest.approx(0.15) == _BOUNDARY_DROP_THRESHOLD
    assert _detect_boundaries(_THREE_TOPIC_SIMS) == _EXPECTED_THREE_TOPIC_BOUNDARIES


def test_q1_chosen_params_stay_quiet_on_smooth_prose() -> None:
    assert _detect_boundaries(_SMOOTH_PROSE_SIMS) == []


def test_q1_alternative_window_5_misses_first_topic_boundary() -> None:
    """``window=5`` swallows the first topic shift into its warm-up region."""
    alt = _detect_boundaries(_THREE_TOPIC_SIMS, window=5, drop=0.15)
    assert 5 not in alt, (
        "window=5 should miss the sentence-5 boundary because its warm-up "
        "window covers sims 0..4 — the first inter-topic drop at i=4 is "
        "still in warm-up."
    )


def test_q1_alternative_drop_010_overfires_on_smooth_prose() -> None:
    """``drop=0.10`` fires on the single dip in the smooth-prose fixture."""
    alt = _detect_boundaries(_SMOOTH_PROSE_SIMS, window=3, drop=0.10)
    assert alt, (
        "drop=0.10 should fire on the 0.78 dip because 0.78 < mean(0.95, "
        "0.93, 0.91) - 0.10 = 0.83 — a false positive on smooth prose."
    )


# --- min/max bound enforcement ----------------------------------------------


def test_enforce_size_bounds_merges_below_min_into_neighbour() -> None:
    sentences = ["four word sentence here", "five word sentence here also"]
    similarities = [0.5]
    result = _enforce_size_bounds([[0], [1]], sentences, similarities)
    assert result == [[0, 1]]


def test_enforce_size_bounds_keeps_below_min_when_solo() -> None:
    sentences = ["small piece only"]
    result = _enforce_size_bounds([[0]], sentences, [])
    assert result == [[0]]


def test_enforce_size_bounds_splits_above_max_on_lowest_similarity() -> None:
    big = " ".join(["word"] * 250)
    sentences = [big, big, big]  # 750 words total — over _MAX_TOKENS (500)
    similarities = [0.9, 0.2]  # second seam is the lowest similarity
    result = _enforce_size_bounds([[0, 1, 2]], sentences, similarities)
    # Split at the lowest seam (index 1, between sentences 1 and 2).
    # After splitting, [[0, 1]] is 500 words — exactly at the bound — and
    # [[2]] is 250 words; both are accepted without further recursion.
    assert result == [[0, 1], [2]]


def test_enforce_size_bounds_splits_above_max_recursively() -> None:
    big = " ".join(["word"] * 200)
    sentences = [big] * 4  # 800 words total
    similarities = [0.5, 0.5, 0.5]
    result = _enforce_size_bounds([[0, 1, 2, 3]], sentences, similarities)
    # Each final chunk must be at most _MAX_TOKENS words.
    for group in result:
        words = sum(len(sentences[i].split()) for i in group)
        assert words <= _MAX_TOKENS


def test_enforce_size_bounds_single_oversized_sentence_is_not_split() -> None:
    huge = " ".join(["word"] * 800)
    result = _enforce_size_bounds([[0]], [huge], [])
    assert result == [[0]]


def test_chunk_document_below_min_chunks_merge_in_three_topic_text() -> None:
    """No final chunk drops below ``_MIN_TOKENS`` unless it is the *only* chunk."""
    text = _three_topic_text()
    records = chunk_document(text, _topic_embed)
    for record in records:
        assert len(record.content.split()) >= _MIN_TOKENS or len(records) == 1


def test_chunk_document_produces_chunk_record_named_tuple() -> None:
    records = chunk_document(_three_topic_text(), _topic_embed)
    assert all(isinstance(r, ChunkRecord) for r in records)
    assert all(isinstance(r.embedding, list) for r in records)
    assert all(isinstance(v, float) for r in records for v in r.embedding)
