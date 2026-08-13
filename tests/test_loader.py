from prometheux_cli.loader import LocalOntology, select_ontologies


def _p(slug, name, pid):
    return LocalOntology(slug=slug, id=pid, name=name, scope="user")


PROJECTS = [
    _p("credit-risk", "Credit Risk", "111"),
    _p("fraud", "Fraud Detection", "222"),
]


def test_no_selectors_returns_all():
    matched, unknown = select_ontologies(PROJECTS, ())
    assert matched == PROJECTS
    assert unknown == []


def test_match_by_name_slug_id():
    assert select_ontologies(PROJECTS, ["Credit Risk"])[0] == [PROJECTS[0]]
    assert select_ontologies(PROJECTS, ["fraud"])[0] == [PROJECTS[1]]
    assert select_ontologies(PROJECTS, ["222"])[0] == [PROJECTS[1]]


def test_unknown_reported():
    matched, unknown = select_ontologies(PROJECTS, ["nope", "fraud"])
    assert matched == [PROJECTS[1]]
    assert unknown == ["nope"]


def test_dedupe_when_name_and_id_both_match():
    matched, _ = select_ontologies(PROJECTS, ["Credit Risk", "111"])
    assert matched == [PROJECTS[0]]
