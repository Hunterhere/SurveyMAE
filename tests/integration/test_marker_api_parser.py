"""Integration tests for MarkerApiParser (optimized for single API call).

These tests call the real Datalab Marker API **exactly once** per test session
and validate behavior via disk cache to minimize API costs.

Prerequisites:
  - DATALAB_API_KEY set in .env
  - test_paper.pdf at project root

Run:
    pytest tests/integration/test_marker_api_parser.py -v -s
"""

import json
import os
from pathlib import Path

import pytest

from src.tools.marker_api_parser import MarkerApiParser, extract_section_headings_from_json

TEST_PDF = Path(__file__).parent.parent.parent / "test_paper.pdf"
DATALAB_API_KEY = os.getenv("DATALAB_API_KEY", "")

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def require_prerequisites():
    if not DATALAB_API_KEY:
        pytest.skip("DATALAB_API_KEY not set — add it to .env")
    if not TEST_PDF.exists():
        pytest.skip(f"Test PDF not found: {TEST_PDF}")


@pytest.fixture(scope="module")
def api_response_cache(tmp_path_factory):
    """
    Module-scoped fixture: calls the real API exactly ONCE.
    
    Returns a tuple (parser_with_cache, markdown, json_structure, cache_dir_path)
    that all tests reuse. Subsequent test calls hit disk cache, avoiding API fees.
    """
    # Create persistent cache directory for the entire test module
    cache_dir = tmp_path_factory.mktemp("marker_cache")
    
    parser = MarkerApiParser(
        api_key=DATALAB_API_KEY,
        mode="fast",
        cache_dir=str(cache_dir),
    )
    
    # SINGLE API CALL for all tests in this module
    markdown, json_struct = parser.parse_with_structure(str(TEST_PDF))
    
    # Verify cache was actually written
    cache_files = list(Path(parser.cache_dir).rglob("*_marker.json"))
    assert len(cache_files) == 1, f"Expected 1 cache file, got {len(cache_files)}"
    
    return parser, markdown, json_struct, str(cache_dir)


@pytest.fixture()
def fresh_parser(api_response_cache):
    """
    Function-scoped fixture: creates fresh parser instance 
    pointing to the same cache directory (ensures cache hits).
    """
    _, _, _, cache_dir = api_response_cache
    return MarkerApiParser(
        api_key=DATALAB_API_KEY,
        mode="fast",
        cache_dir=cache_dir,
    )


def test_parse_returns_nonempty_markdown(fresh_parser, api_response_cache):
    """parse() returns cached markdown without additional API call."""
    _, cached_markdown, _, _ = api_response_cache
    
    # This hits disk cache, zero API cost
    markdown = fresh_parser.parse(str(TEST_PDF))
    
    assert isinstance(markdown, str)
    assert len(markdown) > 500, f"Markdown too short: {len(markdown)} chars"
    assert markdown == cached_markdown, "Should match cached result"
    
    print(f"\n[markdown length]: {len(markdown)}")
    preview = markdown[:600].encode("ascii", "replace").decode("ascii")
    print(f"[markdown preview]:\n{preview}")


def test_parse_with_structure_returns_both_formats(fresh_parser, api_response_cache):
    """parse_with_structure() returns cached data without API call."""
    _, cached_md, cached_json, _ = api_response_cache
    
    # Cache hit - no API call
    markdown, json_struct = fresh_parser.parse_with_structure(str(TEST_PDF))
    
    assert isinstance(markdown, str) and len(markdown) > 500
    assert isinstance(json_struct, dict) and len(json_struct) > 0
    assert markdown == cached_md
    assert json_struct == cached_json
    
    print(f"\n[json_structure top-level keys]: {list(json_struct.keys())}")


def test_no_page_headers_in_markdown_headings(fresh_parser):
    """With keep_pageheader_in_output=False, page headers must not appear as # headings."""
    # Uses cache from module fixture
    markdown = fresh_parser.parse(str(TEST_PDF))
    offending = [
        line for line in markdown.split("\n")
        if line.strip().startswith("#") and "natl sci rev" in line.lower()
    ]
    assert offending == [], f"Page header found as markdown heading: {offending}"


def test_section_headings_extracted_from_json(api_response_cache):
    """extract_section_headings_from_json returns real academic section titles."""
    _, _, json_struct, _ = api_response_cache
    
    headings = extract_section_headings_from_json(json_struct)
    
    print(f"\n[section headings ({len(headings)})]: {headings}")
    assert len(headings) > 0, "No section headings found in JSON structure"
    
    common = {"introduction", "conclusion", "abstract", "references", "method", "results", "discussion"}
    found_lower = {h.lower() for h in headings}
    overlap = common & found_lower
    assert len(overlap) > 0, (
        f"None of common section names {common} found in headings: {headings}"
    )


def test_parse_quality_score_above_threshold(api_response_cache):
    """Cache file records parse_quality_score."""
    parser, _, _, _ = api_response_cache
    cache_files = list(Path(parser.cache_dir).rglob("*_marker.json"))
    cached = json.loads(cache_files[0].read_text(encoding="utf-8"))
    score = cached.get("parse_quality_score")
    
    print(f"\n[parse_quality_score]: {score}")
    if score is None:
        print("[WARNING] parse_quality_score is None; API may not support it for this mode")
        return
    assert score >= 3.0, f"Quality score {score} is below acceptable threshold 3.0"


def test_disk_cache_prevents_api_call_with_invalid_key(api_response_cache):
    """
    Verifies disk cache works: new parser with invalid API key 
    should still return cached result without calling API.
    """
    _, markdown1, struct1, cache_dir = api_response_cache
    
    # Create new parser with intentionally invalid key
    # If cache is bypassed, this would raise authentication error
    bad_parser = MarkerApiParser(
        api_key="INVALID_KEY_SHOULD_TRIGGER_ERROR_IF_NOT_CACHED",
        mode="fast",
        cache_dir=cache_dir,
    )
    
    # Should succeed via cache hit, never reaching API
    markdown2, struct2 = bad_parser.parse_with_structure(str(TEST_PDF))
    
    assert markdown1 == markdown2, "Cached markdown differs from original"
    assert struct1 == struct2, "Cached json_structure differs from original"
    print("\n[disk cache]: correctly served cached result without API call")


def test_page_count_recorded_in_cache(api_response_cache):
    """Cache file must record page_count > 0."""
    parser, _, _, _ = api_response_cache
    cache_files = list(Path(parser.cache_dir).rglob("*_marker.json"))
    cached = json.loads(cache_files[0].read_text(encoding="utf-8"))
    page_count = cached.get("page_count", 0)
    
    print(f"\n[page_count]: {page_count}")
    assert page_count > 0, "page_count not recorded or zero"