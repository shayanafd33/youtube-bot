"""Prints your Buffer channel IDs. Usage: BUFFER_API_KEY=... python buffer_channels.py
Query shape is based on Buffer's docs; if it errors, run the same idea in https://developers.buffer.com/explorer.html"""
import os, json, requests
H = {"Authorization": f"Bearer {os.environ['BUFFER_API_KEY']}"}
def gql(q): return requests.post("https://api.buffer.com", json={"query": q}, headers=H, timeout=60).json()
orgs = gql("query { account { organizations { id name } } }")
print(json.dumps(orgs, indent=1))
for o in orgs["data"]["account"]["organizations"]:
    print(o["name"], json.dumps(gql('query { channels(input: {organizationId: "%s"}) { id name service } }' % o["id"]), indent=1))
