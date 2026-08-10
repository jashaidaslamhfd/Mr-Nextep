import os
import requests
import time

TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT")
REPO = "jashaidaslamhfd/SKILLOR"

headers = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

# 1. Workflow IDs and paths
# Metadata Repair (one-shot) -> id: 319159909, path: .github/workflows/metadata_repair.yml
# SKILLOR - Meta (FB/IG) Strong SEO Repair -> id: 324252141, path: .github/workflows/meta_seo_repair.yml
# US SEO Sweep (descriptions + hashtags) -> id: 321290764, path: .github/workflows/us_seo_sweep.yml
# FB Cover Backfill (match by full caption) -> id: 321344439, path: .github/workflows/fb_cover_backfill.yml

dispatches = [
    {
        "name": "US SEO Sweep (descriptions + hashtags)",
        "id": 321290764,
        "inputs": {"apply": True, "limit": "0"}
    },
    {
        "name": "Metadata Repair (one-shot)",
        "id": 319159909,
        "inputs": {"apply": True, "limit": "0"}
    },
    {
        "name": "SKILLOR - Meta (FB/IG) Strong SEO Repair",
        "id": 324252141,
        "inputs": {"apply": True, "limit": "0"} # meta_seo_repair expects string "0" for input limit
    },
    {
        "name": "FB Cover Backfill (match by full caption)",
        "id": 321344439,
        "inputs": {"apply": True, "min_overlap": "3"}
    }
]

def trigger_workflow(dispatch):
    url = f"https://api.github.com/repos/{REPO}/actions/workflows/{dispatch['id']}/dispatches"
    payload = {
        "ref": "main",
        "inputs": dispatch["inputs"]
    }
    
    print(f"🔄 Triggering '{dispatch['name']}' on main branch...")
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 204:
        print("  ✅ Successfully triggered!")
    else:
        print(f"  ❌ Failed (Status Code {response.status_code}): {response.text}")

if __name__ == "__main__":
    print("=" * 70)
    print("SKILLOR REMOTE METADATA REPAIR DISPATCH")
    print("=" * 70)
    for dispatch in dispatches:
        trigger_workflow(dispatch)
        # Sleep a bit to avoid hitting rate limits or triggering too fast
        time.sleep(3)
    print("=" * 70)
