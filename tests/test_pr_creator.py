from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents import pr_creator

BOT = "synkron-docs[bot]"


def _agent(author: str | None):
    client = MagicMock()
    client.branch_exists = AsyncMock(return_value=True)
    client.get_branch_author = AsyncMock(return_value=author)
    client.commit_files = AsyncMock()
    client.find_pull_request = AsyncMock(
        return_value={"html_url": "https://github.com/acme/w/pull/5", "number": 5})
    client.create_pull_request = AsyncMock()
    client.add_labels = AsyncMock()
    updates = [{"doc_path": "README.md", "updated_content": "x", "explanation": "y"}]
    return pr_creator.PRCreatorAgent(client, "a" * 40, updates, {"summary": "s"}), client


@pytest.fixture(autouse=True)
def bot_login(monkeypatch):
    monkeypatch.setattr(pr_creator, "get_app_bot_login", AsyncMock(return_value=BOT))
    monkeypatch.setattr(pr_creator, "call_gemini", AsyncMock(return_value="desc"))


@pytest.mark.asyncio
@pytest.mark.parametrize("author", ["dependabot[bot]", "github-actions[bot]", "octocat", None])
async def test_existing_branch_from_another_author_is_not_reused(author):
    agent, client = _agent(author)
    with pytest.raises(RuntimeError):
        await agent.run()
    client.commit_files.assert_not_called()


@pytest.mark.asyncio
async def test_existing_branch_from_synkron_bot_is_reused():
    agent, client = _agent(BOT)
    pr = await agent.run()
    client.commit_files.assert_awaited_once()
    assert pr["number"] == 5


@pytest.mark.asyncio
async def test_bot_login_uses_setting_or_cached_app_slug(monkeypatch):
    from app.config import settings
    from app.services import github_auth

    monkeypatch.setattr(settings, "GITHUB_APP_BOT_LOGIN", "custom[bot]")
    assert await github_auth.get_app_bot_login() == "custom[bot]"

    monkeypatch.setattr(settings, "GITHUB_APP_BOT_LOGIN", "")
    monkeypatch.setattr(github_auth, "_bot_login", None)
    resp = MagicMock()
    resp.json.return_value = {"slug": "synkron-docs"}
    app_request = AsyncMock(return_value=resp)
    monkeypatch.setattr(github_auth, "app_request", app_request)
    assert await github_auth.get_app_bot_login() == "synkron-docs[bot]"
    assert await github_auth.get_app_bot_login() == "synkron-docs[bot]"
    app_request.assert_awaited_once()   # looked up once, then cached
