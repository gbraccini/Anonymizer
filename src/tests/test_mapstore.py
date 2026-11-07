import json
from copy import deepcopy

import pytest

from anonymizer.mapstore import dumps, loads
from anonymizer.model import PageResult
from anonymizer.text_pipeline import analyze_text


def sample():
    return analyze_text([PageResult("p", "s", 0, "Elvio Veltrani; e\u0301 😀")]).result.map


def test_map_round_trip_preserves_observed_values_and_ids():
    mapping = sample()
    assert loads(dumps(mapping)) == mapping


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.update(schema_version=2),
        lambda data: data.update(schema_version=True),
        lambda data: data.update(unknown="field"),
        lambda data: data.update(document_id=""),
        lambda data: data["entries"][0].update(token="PERSONA_1"),
        lambda data: data["entries"][0].update(observed_values=[]),
        lambda data: data["entries"][0].update(replacement_ids=["missing"]),
        lambda data: data["replacements"][0].update(start=True),
        lambda data: data["replacements"][0].update(end=1),
        lambda data: data["replacements"][0].update(entity_id="missing"),
        lambda data: data["entries"].append(deepcopy(data["entries"][0])),
        lambda data: data["replacements"].append(deepcopy(data["replacements"][0])),
        lambda data: data.update(entries=[]),
    ],
)
def test_malformed_maps_are_rejected(mutation):
    data = json.loads(dumps(sample()))
    mutation(data)
    with pytest.raises(ValueError, match="Invalid transformation map"):
        loads(json.dumps(data))


@pytest.mark.parametrize("raw", ["null", "[]", "{}", "bad json", "42"])
def test_nonobjects_are_rejected(raw):
    with pytest.raises(ValueError):
        loads(raw)
