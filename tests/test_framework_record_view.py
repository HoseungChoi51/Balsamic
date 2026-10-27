"""Bounded record navigation preserves exact evidence and campaign isolation."""
from copy import deepcopy
import json

import pytest

from optimization_framework.campaigns.record_view import RECORD_VIEW_LIMIT, view_record


def size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def test_small_values_and_escaped_deep_pointers_remain_exact():
    value = {"a/b~c": {"": [{"id": "passage", "capture_id": "capture", "text": "Exact evidence"}]}}
    original = deepcopy(value)
    assert view_record(value, record_id="record") == value
    assert view_record(value, record_id="record", pointer="/a~1b~0c//0") == value["a/b~c"][""][0]
    deep = {"evidence": value}
    pointer = "/evidence"
    for _ in range(40):
        deep = {"level": deep}
        pointer = "/level" + pointer
    assert view_record(deep, record_id="deep", pointer=pointer) == value
    assert value == original


@pytest.mark.parametrize("pointer", ["without-slash", "/a~2b", "/array/-1", "/array/01", "/array/-", "/array/1", "/array/" + "9" * 5000, "/array/0/other"])
def test_invalid_pointers_cannot_use_python_negative_index_or_ambiguous_escapes(pointer):
    with pytest.raises(ValueError):
        view_record({"array": ["only"]}, record_id="record", pointer=pointer)


def test_large_dictionary_index_and_array_pages_are_bounded_and_replayable():
    value = {"body": [{"id": f"row-{i}", "text": "measurement " * 150} for i in range(70)],
             "large/field": {f"key-{i}": "x" * 1000 for i in range(80)}}
    original = deepcopy(value)
    index = view_record(value, record_id="large")
    assert index["record_projection"] == "field_index"
    assert {row["pointer"] for row in index["fields"]} == {"/body", "/large~1field"}
    assert size(index) <= RECORD_VIEW_LIMIT
    offset, restored = 0, []
    while True:
        page = view_record(value, record_id="large", pointer="/body", offset=offset, limit=4)
        assert page["record_projection"] == "array_page" and size(page) <= RECORD_VIEW_LIMIT
        assert page["offset"] == offset and len(page["items"]) <= 4
        restored.extend(page["items"])
        if page["next_offset"] is None:
            break
        assert page["next_offset"] > offset
        offset = page["next_offset"]
    assert restored == value["body"]
    fields, offset = [], 0
    while True:
        page = view_record(value, record_id="large", pointer="/large~1field", offset=offset, limit=7)
        assert page["record_projection"] == "field_index" and size(page) <= RECORD_VIEW_LIMIT
        fields.extend(row["key"] for row in page["fields"])
        if page["next_offset"] is None:
            break
        offset = page["next_offset"]
    assert fields == list(value["large/field"])
    assert value == original


def test_utf8_text_pages_reconstruct_exact_text_without_claiming_full_passage():
    text = ('초격자 🧪 "quoted"\n' * 3500) + "END"
    passage = {"id": "passage", "capture_id": "capture", "text": text}
    index = view_record(passage, record_id="passage")
    assert index["record_projection"] == "field_index" and "text_chunk" not in index
    offset, chunks = 0, []
    while True:
        page = view_record(passage, record_id="passage", pointer="/text", offset=offset)
        assert page["record_projection"] == "text_page" and size(page) <= RECORD_VIEW_LIMIT
        assert page["text_chunk"] == text[offset:offset + len(page["text_chunk"]) ]
        chunks.append(page["text_chunk"])
        if page["next_offset"] is None:
            break
        assert page["next_offset"] > offset
        offset = page["next_offset"]
    assert "".join(chunks) == text


def test_huge_array_child_is_explicit_reference_with_replay_pointer():
    value = [{"id": "huge", "data": "x" * 100_000}]
    page = view_record(value, record_id="array")
    child = page["items"][0]
    assert child["record_projection"] == "reference"
    assert child["read_arguments"]["pointer"] == "/0"
    assert size(page) <= RECORD_VIEW_LIMIT
    fields = view_record(value, **child["read_arguments"])
    assert fields["record_projection"] == "field_index"
    assert {row["key"] for row in fields["fields"]} == {"id", "data"}


def test_explicit_entry_limit_pages_even_small_arrays_and_object_indexes():
    array = [{"value": i} for i in range(10)]
    first = view_record(array, record_id="small_array", limit=1)
    assert first["record_projection"] == "array_page"
    assert first["items"] == array[:1] and first["next_offset"] == 1
    last = view_record(array, record_id="small_array", offset=9, limit=1)
    assert last["record_projection"] == "array_page"
    assert last["items"] == array[9:] and last["next_offset"] is None
    indexed = view_record({str(i): i for i in range(10)}, record_id="small_object", limit=2)
    assert indexed["record_projection"] == "field_index"
    assert [field["key"] for field in indexed["fields"]] == ["0", "1"] and indexed["next_offset"] == 2
