from __future__ import annotations

import json
from pathlib import Path

from a2ui_demo.ontology_models import OntologySpec
from a2ui_demo.ontology_validation import validate_ontology_full, validate_ontology_semantics


def test_validate_sam_credit_card_file() -> None:
    p = Path(__file__).resolve().parents[2] / "ontology" / "sam_credit_card.json"
    spec, errs = validate_ontology_full(p.read_text(encoding="utf-8"))
    assert spec is not None
    assert errs == []


def test_semantic_unknown_logic_ref() -> None:
    data = json.loads(
        Path(__file__).resolve().parents[2].joinpath("ontology", "sam_credit_card.json").read_text(
            encoding="utf-8"
        )
    )
    data["nodes"][0]["logicRef"] = "nonexistent"
    spec = OntologySpec.model_validate(data)
    errs = validate_ontology_semantics(spec)
    assert any("logicRef" in e.get("path", "") for e in errs)


def test_validate_full_returns_errors_for_bad_json() -> None:
    spec, errs = validate_ontology_full("{not json")
    assert spec is None
    assert errs


def test_path_placeholder_must_match_object_property() -> None:
    import json
    from pathlib import Path

    p = Path(__file__).resolve().parents[2] / "ontology" / "sam_credit_card.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["logicDefinitions"][0]["implementation"]["requestPathTemplate"] = "/api/x/{unknownAttr}"
    spec = OntologySpec.model_validate(data)
    from a2ui_demo.ontology_validation import validate_ontology_semantics

    errs = validate_ontology_semantics(spec)
    assert any("requestPathTemplate" in e.get("path", "") for e in errs)

