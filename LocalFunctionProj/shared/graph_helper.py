from azure.identity.aio import ClientSecretCredential
from azure.identity import DeviceCodeCredential
from msgraph import GraphServiceClient
import os

APP_ID = os.getenv("MicrosoftAppId", "")
APP_SECRET = os.getenv("MicrosoftAppPassword", "")
TENANT_ID = os.getenv("TenantId", "")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"

async def get_graph_client():
    """
    Get Microsoft Graph client.
    First tries application permissions (organizational accounts),
    then falls back to personal account handling.
    """
    # For organizational accounts with SharePoint Online licensing
    credential = ClientSecretCredential(
        tenant_id=TENANT_ID,
        client_id=APP_ID, 
        client_secret=APP_SECRET
    )
    scopes = ["https://graph.microsoft.com/.default"]
    return GraphServiceClient(credentials=credential, scopes=scopes)

async def get_graph_client_personal():
    """
    Alternative method for personal Microsoft accounts.
    Uses different tenant configuration for personal accounts.
    """
    # For personal accounts, use 'common' or 'consumers' tenant
    personal_tenant = "common"  # or "consumers" for personal accounts only
    
    credential = ClientSecretCredential(
        tenant_id=personal_tenant,
        client_id=APP_ID, 
        client_secret=APP_SECRET
    )
    # Use more specific scopes for personal accounts
    scopes = ["https://graph.microsoft.com/Files.Read.All", "https://graph.microsoft.com/User.Read"]
    return GraphServiceClient(credentials=credential, scopes=scopes)
