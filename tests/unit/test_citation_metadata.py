"""Unit tests for citation metadata comparison."""

from src.tools.citation_metadata import BibEntry, CitationMetadataChecker


def test_compare_metadata_match():
    """Metadata comparison should match on identical title/authors/year."""
    bib_entry = BibEntry(
        key="vaswani2017attention",
        title="Attention Is All You Need",
        author="Vaswani, Ashish and Shazeer, Noam",
        year="2017",
    )

    metadata = {
        "title": "Attention Is All You Need",
        "authors": ["Ashish Vaswani", "Noam Shazeer"],
        "year": "2017",
    }

    checker = CitationMetadataChecker()
    result = checker.compare_metadata(bib_entry, metadata, source="crossref")

    assert result.is_match is True
    assert result.title_match is True
    assert result.author_match is True
    assert result.year_match is True
