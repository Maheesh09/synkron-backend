# scripts/preflight.py — proves the GitHub App auth chain works end to end.
import asyncio
from app.config import settings
from app.services import github_auth as ga


async def main():
    print("App ID:            ", settings.GITHUB_APP_ID or "*** MISSING ***")
    print("Webhook secret set:", bool(settings.GITHUB_WEBHOOK_SECRET))

    pem_first_line = ga._load_private_key().splitlines()[0]
    print("Private key loads: ", pem_first_line)

    resp = await ga.app_request("GET", "/app/installations")
    installs = resp.json()
    if not installs:
        print("\nNo installations yet — install the App on a test repo, then re-run.")
        return
    print("\nInstallations:")
    for inst in installs:
        print(f"  installation_id={inst['id']}  "
              f"account={inst['account']['login']}  "
              f"selection={inst.get('repository_selection')}")


if __name__ == "__main__":
    asyncio.run(main())