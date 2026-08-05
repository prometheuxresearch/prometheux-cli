from prometheux_cli.loader import LocalProject, select_projects


def _p(slug, name, pid):
    return LocalProject(slug=slug, id=pid, name=name, scope="user")


PROJECTS = [
    _p("credit-risk", "Credit Risk", "111"),
    _p("fraud", "Fraud Detection", "222"),
]


def test_no_selectors_returns_all():
    matched, unknown = select_projects(PROJECTS, ())
    assert matched == PROJECTS
    assert unknown == []


def test_match_by_name_slug_id():
    assert select_projects(PROJECTS, ["Credit Risk"])[0] == [PROJECTS[0]]
    assert select_projects(PROJECTS, ["fraud"])[0] == [PROJECTS[1]]
    assert select_projects(PROJECTS, ["222"])[0] == [PROJECTS[1]]


def test_unknown_reported():
    matched, unknown = select_projects(PROJECTS, ["nope", "fraud"])
    assert matched == [PROJECTS[1]]
    assert unknown == ["nope"]


def test_dedupe_when_name_and_id_both_match():
    matched, _ = select_projects(PROJECTS, ["Credit Risk", "111"])
    assert matched == [PROJECTS[0]]
