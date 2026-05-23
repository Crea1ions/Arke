from __future__ import annotations

from arke.interfaces.mcp_servers import github as github_mod


async def _fake_request_ok(_url, headers=None):  # noqa: ARG001
    body = '{"login":"Crea1ons","name":"Crea1ons","bio":"bio","public_repos":12,"followers":2,"following":1,"blog":"","html_url":"https://github.com/Crea1ons"}'
    return 200, body


async def _fake_request_not_found(_url, headers=None):  # noqa: ARG001
    return 404, '{"message":"Not Found"}'


def test_github_mcp_initializes_without_httpx(monkeypatch):
    monkeypatch.setattr(github_mod, "httpx", None)

    server = github_mod.GitHubMCP()

    assert server.client is None


def test_github_user_works_with_stdlib_fallback(monkeypatch):
    monkeypatch.setattr(github_mod, "httpx", None)

    server = github_mod.GitHubMCP()
    monkeypatch.setattr(server, "_request", _fake_request_ok)

    out = github_mod.asyncio.run(server.get_user("Crea1ons"))

    assert out["success"] is True
    assert out["login"] == "Crea1ons"
    assert out["public_repos"] == 12


def test_github_user_returns_http_error(monkeypatch):
    monkeypatch.setattr(github_mod, "httpx", None)

    server = github_mod.GitHubMCP()
    monkeypatch.setattr(server, "_request", _fake_request_not_found)

    out = github_mod.asyncio.run(server.get_user("missing-user"))

    assert out["success"] is False
    assert out["error"] == "HTTP 404"


def test_github_repo_parses_full_url_and_fetches_repo(monkeypatch):
    monkeypatch.setattr(github_mod, "httpx", None)
    server = github_mod.GitHubMCP()

    captured = {}

    async def _fake_get_repo(owner, repo):
        captured["owner"] = owner
        captured["repo"] = repo
        return {"success": True, "name": f"{owner}/{repo}"}

    monkeypatch.setattr(server, "get_repo", _fake_get_repo)

    out = github_mod.asyncio.run(
        server.handle_tool("github_repo", {"url": "https://github.com/Crea1ions/MyTeamHub"})
    )

    assert out["success"] is True
    assert captured["owner"] == "Crea1ions"
    assert captured["repo"] == "MyTeamHub"


def test_github_repo_falls_back_to_user_repos_when_repo_missing(monkeypatch):
    monkeypatch.setattr(github_mod, "httpx", None)
    server = github_mod.GitHubMCP()

    async def _fake_user(username):
        return {"success": True, "login": username}

    async def _fake_user_repos(username, max_results=5, sort="updated"):
        return {
            "success": True,
            "repositories": [{"full_name": f"{username}/repo1"}],
            "count": 1,
        }

    monkeypatch.setattr(server, "get_user", _fake_user)
    monkeypatch.setattr(server, "get_user_repos", _fake_user_repos)

    out = github_mod.asyncio.run(server.handle_tool("github_repo", {"owner": "Crea1ions"}))

    assert out["success"] is True
    assert out["mode"] == "user_repos_fallback"
    assert out["count"] == 1
    assert out["repositories"][0]["full_name"] == "Crea1ions/repo1"


def test_github_user_accepts_profile_url(monkeypatch):
    monkeypatch.setattr(github_mod, "httpx", None)
    server = github_mod.GitHubMCP()

    captured = {}

    async def _fake_get_user(username):
        captured["username"] = username
        return {"success": True, "login": username}

    monkeypatch.setattr(server, "get_user", _fake_get_user)

    out = github_mod.asyncio.run(
        server.handle_tool("github_user", {"url": "https://github.com/Crea1ions/"})
    )

    assert out["success"] is True
    assert captured["username"] == "Crea1ions"


def test_github_readme_parses_full_repo_url(monkeypatch):
    monkeypatch.setattr(github_mod, "httpx", None)
    server = github_mod.GitHubMCP()

    captured = {}

    async def _fake_get_readme(owner, repo, branch="HEAD"):
        captured["owner"] = owner
        captured["repo"] = repo
        captured["branch"] = branch
        return {"success": True, "content": "# MyTeamHub", "length": 11, "truncated": False}

    monkeypatch.setattr(server, "get_readme", _fake_get_readme)

    out = github_mod.asyncio.run(
        server.handle_tool("github_readme", {"url": "https://github.com/Crea1ions/MyTeamHub"})
    )

    assert out["success"] is True
    assert captured["owner"] == "Crea1ions"
    assert captured["repo"] == "MyTeamHub"
    assert captured["branch"] == "HEAD"


def test_github_readme_falls_back_to_exact_repo_name_search(monkeypatch):
    monkeypatch.setattr(github_mod, "httpx", None)
    server = github_mod.GitHubMCP()

    captured = {}

    async def _fake_search_repos(query, max_results=5, sort="stars"):
        return [
            {"name": "Crea1ions/MyTeamHub", "full_name": "Crea1ions/MyTeamHub"},
            {"name": "someone-else/OtherRepo", "full_name": "someone-else/OtherRepo"},
        ]

    async def _fake_get_readme(owner, repo, branch="HEAD"):
        captured["owner"] = owner
        captured["repo"] = repo
        return {"success": True, "content": "# MyTeamHub"}

    monkeypatch.setattr(server, "search_repos", _fake_search_repos)
    monkeypatch.setattr(server, "get_readme", _fake_get_readme)

    out = github_mod.asyncio.run(server.handle_tool("github_readme", {"repo": "MyTeamHub"}))

    assert out["success"] is True
    assert captured["owner"] == "Crea1ions"
    assert captured["repo"] == "MyTeamHub"
