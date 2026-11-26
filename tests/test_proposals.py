import pytest


@pytest.mark.parametrize("number", [1, 2, 3])
def test_proposal_pages_are_served(client, number):
    redirect = client.get(f"/propuesta{number}", follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["location"] == f"/propuesta{number}/"

    page = client.get(f"/propuesta{number}/")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")

    assert client.get(f"/propuesta{number}/styles.css").status_code == 200
    assert client.get(f"/propuesta{number}/app.js").status_code == 200


def test_proposals_index_links_all_three(client):
    page = client.get("/propuestas")
    assert page.status_code == 200
    for number in (1, 2, 3):
        assert f"/propuesta{number}/" in page.text


@pytest.mark.parametrize(
    "path",
    [
        "/propuesta4/",
        "/propuesta1/../proposals.py",
        "/propuesta1/missing.js",
        "/propuesta1/DESIGN.md",
    ],
)
def test_proposal_rejects_unknown_paths(client, path):
    assert client.get(path).status_code == 404
