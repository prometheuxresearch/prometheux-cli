from prometheux_cli.loader import LocalConcept
from prometheux_cli.openlineage import concept_datasets, make_run_event


def _c(pred, body, meta=None):
    return LocalConcept(predicate=pred, concept_type="logic", body=body, meta=meta or {}, path=pred)


def test_concept_datasets_inputs_from_body_and_binds():
    ns = "prometheux://p1"
    c = _c(
        "risk",
        "risk(Id) :- customer(Id, _), source_x(Id).",
        {"binds": {"input": [{"predicate": "source_x", "datasource": "snowflake_prod"}]}},
    )
    inputs, outputs = concept_datasets(c, {"risk", "customer"}, ns)
    names = {d["name"] for d in inputs}
    assert "customer" in names          # upstream concept (derived edge)
    assert "snowflake_prod" in names    # bound datasource
    assert "source_x" not in names      # not a local concept, not a datasource ref by name
    assert outputs == [{"namespace": ns, "name": "risk"}]


def test_make_run_event_start():
    ev = make_run_event(
        event_type="START", run_id="r1", event_time="2026-01-01T00:00:00Z",
        job_namespace="prometheux", job_name="proj.risk",
        inputs=[{"namespace": "ns", "name": "customer"}],
        outputs=[{"namespace": "ns", "name": "risk"}],
    )
    assert ev["eventType"] == "START"
    assert ev["run"]["runId"] == "r1"
    assert ev["job"] == {"namespace": "prometheux", "name": "proj.risk"}
    assert ev["run"]["facets"] == {}
    assert ev["producer"].endswith(tuple("0123456789"))  # version-suffixed


def test_make_run_event_fail_has_error_facet():
    ev = make_run_event(
        event_type="FAIL", run_id="r1", event_time="t",
        job_namespace="prometheux", job_name="j",
        inputs=[], outputs=[], error_message="boom",
    )
    assert ev["eventType"] == "FAIL"
    assert ev["run"]["facets"]["errorMessage"]["message"] == "boom"
