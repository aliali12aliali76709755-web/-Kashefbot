import os, json, urllib.request

base = os.environ["INTEGRATION_PROXY_URL"]
job_id = "20e3e081-3da2-44f3-8074-17554fafd96c"
key = "sk-emergent-934DeD4DeEaCe0c7e1"
req = urllib.request.Request(
    base + "/stripe/sandboxes",
    data=json.dumps({"job_id": job_id}).encode(),
    headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req) as r:
    sandbox = json.load(r)

print(json.dumps({
    "sandbox_secret_key": sandbox.get("sandbox_secret_key"),
    "sandbox_publishable_key": sandbox.get("sandbox_publishable_key"),
    "sandbox_account_id": sandbox.get("sandbox_account_id"),
    "preview_webhook_secret": sandbox.get("preview_webhook_secret"),
    "onboarding_url": sandbox.get("onboarding_url"),
}, indent=2))

import stripe
stripe.api_key = sandbox["sandbox_secret_key"]
print("COUNTRY:", stripe.Account.retrieve()["country"])
