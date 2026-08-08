from __future__ import annotations

from langchain_text_splitters import Language, RecursiveCharacterTextSplitter


def chunk_document(text: str, *, chunk_size: int = 400, chunk_overlap: int = 60) -> list[str]:
    """Markdown-aware recursive chunking (learnings.md #3, decision 4). chunk_size=400/overlap=60
    was picked empirically, not guessed: 800 (the original default) never split any fixture doc,
    which caused topic dilution — a single chunk covering several unrelated facts scores worse
    against a narrow question about just one of them (see the "WFH on Fridays" investigation in
    learnings.md). 300 split cleanly on paragraphs but cut a numbered-list step in half in one
    runbook; 400/60 avoids that while still isolating single-fact paragraphs into their own
    chunks."""

    splitter = RecursiveCharacterTextSplitter.from_language(
        language=Language.MARKDOWN,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return splitter.split_text(text)
