from __future__ import annotations

from enterprise_ai.core.chunking import chunk_document


def test_short_single_paragraph_stays_as_one_chunk():
    text = "# Title\n\nA short single paragraph well under the chunk size."

    chunks = chunk_document(text)

    assert len(chunks) == 1


def test_multi_paragraph_document_splits_into_multiple_chunks():
    paragraph = "This is a reasonably long paragraph written to exceed the default chunk size " * 4
    text = f"# Title\n\n{paragraph}\n\n{paragraph}\n\n{paragraph}"

    chunks = chunk_document(text, chunk_size=400, chunk_overlap=60)

    assert len(chunks) > 1
    assert all(len(chunk) <= 400 + 60 for chunk in chunks)


def test_does_not_split_inside_a_numbered_list_item():
    text = (
        "# Runbook\n\n"
        "1. A short first step.\n"
        "2. A second step that is deliberately written to be long enough that it might "
        "tempt a naive splitter to cut it in half right in the middle of the sentence.\n"
        "3. A short third step.\n"
    )

    chunks = chunk_document(text, chunk_size=400, chunk_overlap=60)

    assert any("tempt a naive splitter to cut it in half right in the middle" in chunk for chunk in chunks)
