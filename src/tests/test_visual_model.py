import json
from dataclasses import replace

import pytest

from anonymizer.manifest import confirm_review, dumps, loads
from anonymizer.model import PageResult
from anonymizer.visual_model import (
    DocumentError,
    ReviewManifest,
    ReviewWarning,
    SourcePageGeometry,
    SourceRecord,
    VisualPage,
    VisualRedaction,
    validate_manifest,
)


def geometry():
    return SourcePageGeometry(100, 80, 100, 80, 72)


def sample():
    mask = VisualRedaction(
        "p", ((2, 2), (10, 2), (10, 10), (2, 10)), origin="automatic", candidate_ids=("c",)
    )
    page = VisualPage(
        PageResult("p", "s", 0, "text"),
        0,
        geometry(),
        (mask,),
        (ReviewWarning("manual_review"),),
        ("c",),
        (mask.id,),
    )
    return ReviewManifest((SourceRecord("s", "a" * 64, "PNG", 0, 1),), (page,), page_order=("p",))


def test_roundtrip_and_confirmation_snapshot():
    manifest = sample()
    assert loads(dumps(manifest)) == manifest
    with pytest.raises(DocumentError, match="unconfirmed"):
        validate_manifest(manifest, reviewed=True)
    approved = confirm_review(manifest)
    validate_manifest(loads(dumps(approved)), reviewed=True)
    modified = replace(
        approved,
        pages=(replace(approved.pages[0], page=replace(approved.pages[0].page, text="changed")),),
    )
    with pytest.raises(DocumentError, match="snapshot_changed"):
        validate_manifest(modified, reviewed=True)


@pytest.mark.parametrize(
    "points",
    [
        ((-1, 0), (4, 0), (4, 4), (0, 4)),
        ((0, 0), (101, 0), (101, 4), (0, 4)),
        ((0, 0), (float("nan"), 0), (4, 4), (0, 4)),
        ((0, 0), (float("inf"), 0), (4, 4), (0, 4)),
        ((0, 0), (4, 4), (4, 0), (0, 4)),
        ((0, 0), (0, 0), (0, 0), (0, 0)),
    ],
)
def test_invalid_polygons_rejected(points):
    with pytest.raises(DocumentError):
        VisualRedaction("p", points).validate(geometry())


def test_missing_one_of_multiple_regions_requires_decision_even_if_candidate_link_survives():
    manifest = sample()
    first = manifest.pages[0].redactions[0]
    second = replace(first, id="second")
    page = replace(
        manifest.pages[0], redactions=(first, second), required_redaction_ids=(first.id, second.id)
    )
    manifest = replace(manifest, pages=(page,))
    damaged = replace(manifest, pages=(replace(page, redactions=(first,)),))
    with pytest.raises(DocumentError, match="missing_redaction_decision"):
        confirm_review(damaged)


def test_manual_geometry_required_for_unmapped_candidate():
    manifest = sample()
    page = replace(
        manifest.pages[0],
        warnings=(ReviewWarning("candidate_geometry_incomplete", candidate_ids=("c",)),),
    )
    with pytest.raises(DocumentError, match="unresolved_candidate_geometry"):
        confirm_review(replace(manifest, pages=(page,)))
    manual = VisualRedaction("p", ((0, 0), (20, 0), (20, 20), (0, 20)), candidate_ids=("c",))
    confirm_review(replace(manifest, pages=(replace(page, redactions=(*page.redactions, manual)),)))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.update(schema_version=True),
        lambda data: data["pages"][0]["geometry"].update(width_points=10**400),
        lambda data: data["pages"][0]["redactions"][0].update(page_id="other"),
        lambda data: data["pages"][0]["warnings"][0].update(acknowledged="false"),
        lambda data: data.update(page_order=[]),
        lambda data: data["pages"].append(data["pages"][0]),
    ],
)
def test_malformed_manifest_is_controlled(mutation):
    data = json.loads(dumps(sample()))
    mutation(data)
    with pytest.raises(DocumentError):
        loads(json.dumps(data))
