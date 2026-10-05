"""Run this ONCE on your laptop to get a YouTube refresh token.

Needs client_secret.json (OAuth client of type "Desktop app") in the repo root.
"""
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

print("\n" + "=" * 60)
print("YT_CLIENT_ID     =", creds.client_id)
print("YT_CLIENT_SECRET =", creds.client_secret)
print("YT_REFRESH_TOKEN =", creds.refresh_token)
print("=" * 60)
print("Save these three values as GitHub Secrets. Never commit them.")
