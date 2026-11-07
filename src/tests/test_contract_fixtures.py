import json
from pathlib import Path

from anonymizer.mapstore import loads
from anonymizer.model import PageResult
from anonymizer.text_pipeline import analyze_text

FIXTURES = Path(__file__).parent / "fixtures"


def test_annotations_match_unicode_codepoint_offsets_and_clinical_text_survives():
    corpus = json.loads((FIXTURES / "text_corpus.json").read_text("utf-8"))
    assert len(corpus["documents"]) == 20
    template_splits = {}
    for document in corpus["documents"]:
        template_splits.setdefault(document["template_id"], set()).add(document["split"])
        pages = [PageResult(**page) for page in document["pages"]]
        page_by_id = {page.page_id: page for page in pages}
        for annotation in document["identifiers"] + document["clinical_invariants"]:
            text = page_by_id[annotation["page_id"]].text
            assert text[annotation["start"] : annotation["end"]] == annotation["observed"]
        result = analyze_text(pages).result
        for annotation in document["identifiers"]:
            assert any(
                operation.page_id == annotation["page_id"]
                and operation.start <= annotation["start"]
                and operation.end >= annotation["end"]
                for operation in result.replacements
            )
        for annotation in document["clinical_invariants"]:
            assert all(
                operation.end <= annotation["start"] or operation.start >= annotation["end"]
                for operation in result.replacements
                if operation.page_id == annotation["page_id"]
            )
    assert all(len(splits) == 1 for splits in template_splits.values())


def test_review_contract_is_self_consistent_and_restorable_by_occurrence():
    contract = json.loads((FIXTURES / "review_contract.json").read_text("utf-8"))
    assert contract["offset_unit"] == "unicode_codepoint"
    mapping = loads(json.dumps(contract["result"]["map"]))
    page = contract["pages"][0]
    output = contract["result"]["pages"][0]["text"]
    for operation in mapping.replacements:
        assert page["text"][operation.start : operation.end] == operation.original
        assert output[operation.result_start : operation.result_end] == operation.replacement
    assert mapping.replacements[0].original != mapping.replacements[1].original
