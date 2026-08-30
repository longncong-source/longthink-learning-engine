"""Project endpoints tests."""

from __future__ import annotations

from cloud.tests.conftest import AUTH_HEADERS


class TestProjects:
    def test_create_list_get(self, client):  # type: ignore[no-untyped-def]
        created = client.post(
            "/v1/projects",
            json={"name": "LNG Project", "description": "Long Nhôn terminal"},
            headers=AUTH_HEADERS,
        )
        assert created.status_code == 201
        project = created.json()
        assert project["name"] == "LNG Project"
        assert project["status"] == "active"

        listed = client.get("/v1/projects", headers=AUTH_HEADERS).json()
        assert any(p["id"] == project["id"] for p in listed)

        fetched = client.get(f"/v1/projects/{project['id']}", headers=AUTH_HEADERS)
        assert fetched.status_code == 200

    def test_duplicate_name_conflicts(self, client):  # type: ignore[no-untyped-def]
        client.post("/v1/projects", json={"name": "Unique Project X"}, headers=AUTH_HEADERS)
        again = client.post("/v1/projects", json={"name": "Unique Project X"}, headers=AUTH_HEADERS)
        assert again.status_code == 409

    def test_memory_requires_existing_project(self, client):  # type: ignore[no-untyped-def]
        created = client.post(
            "/v1/projects", json={"name": "P-with-mem"}, headers=AUTH_HEADERS
        ).json()
        ok = client.post(
            "/v1/memory",
            json={
                "title": "t",
                "content": "c",
                "project_id": created["id"],
            },
            headers=AUTH_HEADERS,
        )
        assert ok.status_code == 201

    def test_validation_empty_name(self, client):  # type: ignore[no-untyped-def]
        resp = client.post("/v1/projects", json={"name": ""}, headers=AUTH_HEADERS)
        assert resp.status_code == 422
