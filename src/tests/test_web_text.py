import copy
import zipfile
from dataclasses import replace
from io import BytesIO

import pytest

pytest.importorskip("PIL")

from anonymizer.model import PageResult, TextRegion  # noqa: E402
from anonymizer.visual_model import VisualPage, VisualRedaction  # noqa: E402
from anonymizer.web.text import page_text  # noqa: E402


def text_page(masks=(), regions=None):
    from test_visual_model import geometry

    text = "Zoë 😀 clinico"
    if regions is None:
        regions = (
            TextRegion(0, 3, (5, 5, 25, 15)),
            TextRegion(4, 5, (30, 5, 40, 15)),
            TextRegion(6, len(text), (45, 5, 85, 15)),
        )
    return VisualPage(PageResult("p", "s", 0, text, regions=regions), 0, geometry(), masks)


def rectangle(box=(5, 5, 25, 15), **kwargs):
    x0, y0, x1, y1 = box
    return VisualRedaction("p", ((x0, y0), (x1, y0), (x1, y1), (x0, y1)), **kwargs)


def test_manual_mask_unicode_rejection_and_overlapping_mask_sync():
    mask = rectangle(origin="manual")
    assert page_text(text_page((mask,))) == {
        "original": "Zoë 😀 clinico",
        "redacted": "[OSCURATO] 😀 clinico",
    }
    rejected = replace(mask, decision="reject", reason="Synthetic review")
    assert page_text(text_page((rejected,)))["redacted"] == "Zoë 😀 clinico"
    overlap = rectangle((20, 12, 27, 18), origin="manual")
    assert page_text(text_page((rejected, overlap)))["redacted"] == "[OSCURATO] 😀 clinico"
    emoji = rectangle((30, 5, 40, 15), origin="manual")
    assert page_text(text_page((emoji,)))["redacted"] == "Zoë [OSCURATO] clinico"


def test_whole_ocr_region_is_removed_on_any_footprint_intersection():
    region = TextRegion(0, 13, (5, 5, 85, 15))
    mask = rectangle((80, 10, 90, 20), origin="manual")
    assert page_text(text_page((mask,), (region,)))["redacted"] == "[OSCURATO]"


def test_quad_uses_polygon_footprint_not_bounding_box():
    mask = VisualRedaction("p", ((0, 0), (80, 0), (80, 5), (0, 70)), "manual")
    # Bottom-right of its bounds is outside this trapezoid and its boundary stroke.
    region = TextRegion(0, 13, (60, 55, 75, 65))
    assert page_text(text_page((mask,), (region,)))["redacted"] == "Zoë 😀 clinico"


def test_preview_lines_share_unicode_overlap_states_with_full_text():
    page = text_page(
        (rectangle((20, 10, 27, 18), origin="manual"),),
        (
            TextRegion(0, 3, (5, 5, 25, 15)),
            TextRegion(0, 5, (5, 5, 40, 15)),
            TextRegion(6, 13, (45, 5, 85, 15)),
        ),
    )
    result = page_text(page, include_lines=True)
    assert result["lines"] == [
        dict(
            original="Zoë 😀 clinico",
            redacted=result["redacted"],
            bounds=[5, 5, 85, 15],
            unlocalized=False,
        )
    ]
    assert "Zoë" not in result["lines"][0]["redacted"]
    assert "😀" not in result["lines"][0]["redacted"]


def test_preview_lines_keep_unlocalized_text_hidden_and_bounds_clipped():
    page = text_page(regions=(TextRegion(0, 3, (-5, 5, 25, 15)),))
    page = replace(page, page=replace(page.page, text="Zoë\n😀 secret\n"))
    result = page_text(page, include_lines=True)
    assert result["lines"][0] == dict(
        original="Zoë",
        redacted="Zoë",
        bounds=[0, 5, 25, 15],
        unlocalized=False,
    )
    assert result["lines"][1]["bounds"] is None
    assert result["lines"][1]["unlocalized"]
    assert "secret" not in result["lines"][1]["redacted"]
    assert "😀" not in result["lines"][1]["redacted"]


def test_preview_lines_respect_quad_footprint_and_rejected_masks():
    mask = VisualRedaction("p", ((0, 0), (80, 0), (80, 5), (0, 70)), "manual")
    page = text_page((mask,), (TextRegion(0, 13, (60, 55, 75, 65)),))
    assert page_text(page, include_lines=True)["lines"][0]["redacted"] == "Zoë 😀 clinico"
    rejected = replace(rectangle(), decision="reject", reason="Review")
    assert (
        page_text(text_page((rejected,)), include_lines=True)["lines"][0]["redacted"]
        == "Zoë 😀 clinico"
    )


@pytest.mark.parametrize(
    "box", [None, (120, 5, 130, 15), (5, 5, 5, 15), (4.5, 5, 4.5, 15), (float("nan"), 0, 4, 4)]
)
def test_unlocalized_text_never_exposed_and_whitespace_is_preserved(box):
    page = text_page(regions=(TextRegion(0, 3, box),))
    page = replace(page, page=replace(page.page, text="Zoë\n\t"))
    assert page_text(page)["redacted"] == "[TESTO NON LOCALIZZATO]\n\t"


@pytest.fixture
def web_client(monkeypatch):
    pytest.importorskip("fastapi")
    TestClient = pytest.importorskip("fastapi.testclient").TestClient
    from anonymizer.web.app import create_app

    monkeypatch.setattr("anonymizer.web.app.probe_ocr", lambda: "unavailable")
    with TestClient(
        create_app(local_only=True), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)
    ) as client:
        yield client


def ready_review(client):
    from test_web import analyzed, edits_for, fields, post

    analysis = analyzed(client)
    review = edits_for(analysis)
    preview = post(client, "preview", fields(analysis, review)).json()
    review.update(final_confirmation=True, preview_digest=preview["preview_digest"])
    return analysis, review, preview


def test_preview_text_final_copy_and_pdf_text_bundle_share_review(web_client):
    from test_web import fields, post

    analysis, review, preview = ready_review(web_client)
    assert "Elvio" in preview["text"]["original"]
    assert "Hb 12" in preview["text"]["redacted"]
    response = post(web_client, "text-export", fields(analysis, review))
    assert response.status_code == 200
    assert preview["text"]["redacted"] in response.text
    response = post(
        web_client, "export", {**fields(analysis, review), "format": "pdf", "include_text": "true"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {"documento-oscurato.pdf", "testo-oscurato.txt"}
        assert archive.read("documento-oscurato.pdf").startswith(b"%PDF-")
        assert (
            archive.read("testo-oscurato.txt").decode("utf-8")
            == post(web_client, "text-export", fields(analysis, review)).text
        )


def test_text_export_rejects_stale_manual_edit_forged_geometry_and_wrong_source(web_client):
    from test_web import fields, post, source

    analysis, review, _ = ready_review(web_client)
    altered = copy.deepcopy(analysis)
    altered["contract"]["manifest"]["pages"][0]["geometry"]["width"] += 1
    assert post(web_client, "text-export", fields(altered, review)).status_code == 400
    assert (
        post(web_client, "text-export", fields(analysis, review), source("Different")).status_code
        == 400
    )
    item = analysis["contract"]["manifest"]["pages"][0]
    review["manual_masks"].append(
        dict(
            id="manual",
            page_id=item["page"]["page_id"],
            polygon=[[1, 1], [50, 1], [50, 50], [1, 50]],
            confirmed=True,
            candidate_ids=[],
        )
    )
    response = post(web_client, "text-export", fields(analysis, review))
    assert response.json()["error"] == "review_changed_since_preview"


def test_manual_and_reject_review_changes_preview_text_after_new_digest(web_client):
    from test_web import fields, post

    analysis, review, preview = ready_review(web_client)
    item = analysis["contract"]["manifest"]["pages"][0]
    region = next(r for r in item["page"]["regions"] if r["box"])
    x0, y0, x1, y1 = region["box"]
    review["manual_masks"] = [
        dict(
            id="manual",
            page_id=item["page"]["page_id"],
            polygon=[[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
            confirmed=True,
            candidate_ids=[],
        )
    ]
    updated = post(web_client, "preview", fields(analysis, review)).json()
    assert updated["preview_digest"] != preview["preview_digest"]
    assert "[OSCURATO]" in updated["text"]["redacted"]
    # A rejected automatic mask restores only what is not covered by the manual one.
    for decision in review["decisions"].values():
        decision.update(decision="reject", reason="Synthetic document click")
    updated = post(web_client, "preview", fields(analysis, review)).json()
    assert "[OSCURATO]" in updated["text"]["redacted"]
    review["preview_digest"] = updated["preview_digest"]
    assert post(web_client, "text-export", fields(analysis, review)).status_code == 200


def test_page_verification_requires_explicit_decisions_and_acknowledgments(web_client):
    from test_web import analyzed, edits_for, fields, post

    analysis = analyzed(web_client)
    review = edits_for(analysis, confirmed=False)
    preview = post(web_client, "preview", fields(analysis, review)).json()
    review.update(final_confirmation=True, preview_digest=preview["preview_digest"])
    assert post(web_client, "text-export", fields(analysis, review)).status_code == 400
    for decision in review["decisions"].values():
        decision["confirmed"] = True
    review["acknowledgments"] = {}
    preview = post(web_client, "preview", fields(analysis, review)).json()
    review["preview_digest"] = preview["preview_digest"]
    assert post(web_client, "text-export", fields(analysis, review)).status_code == 400
