import os
from msal import ConfidentialClientApplication
from msgraph import GraphServiceClient

APP_ID = os.getenv("MicrosoftAppId")
APP_SECRET = os.getenv("MicrosoftAppPassword")
TENANT_ID = os.getenv("TenantId")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["https://graph.microsoft.com/.default"]

async def get_graph_client():
    app = ConfidentialClientApplication(
        APP_ID, authority=AUTHORITY, client_credential=APP_SECRET
    )
    result = app.acquire_token_for_client(scopes=SCOPES)
    if "access_token" in result:
        credentials = TokenCredential(result["access_token"])
        return GraphServiceClient(credentials=credentials)
    raise Exception("Failed to get access token")

class TokenCredential:
    def __init__(self, token):
        self.token = token

    async def get_token(self, *scopes, **kwargs):
        return self.token, None, None