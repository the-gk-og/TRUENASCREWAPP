#!/usr/bin/env python3
"""Mint a short-lived, single-use support token for ONE instance.

  python support_mint.py --instance greenroom-crew --url https://crew.greenroom.org
  python support_mint.py --instance greenroom-crew --scope admin --minutes 15
"""
import argparse, base64, json, os, time, uuid
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

b64e = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def load_key(path):
    with open(path) as f:
        raw = f.read().strip()
    return Ed25519PrivateKey.from_private_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))


def mint_token(priv, instance, operator="support", scope="readonly", minutes=10, now=None):
    now = int(time.time() if now is None else now)
    payload = {"iss": "showwise-support", "aud": instance, "sub": operator, "scope": scope,
               "iat": now, "exp": now + minutes * 60, "jti": uuid.uuid4().hex}
    pb = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return b64e(pb) + "." + b64e(priv.sign(pb))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", required=True, help="must match the instance's SUPPORT_INSTANCE_ID")
    ap.add_argument("--operator", default="support", help="who is logging in (shown in the audit log)")
    ap.add_argument("--scope", choices=["readonly", "admin"], default="readonly")
    ap.add_argument("--minutes", type=int, default=10, help="token validity, 1-30")
    ap.add_argument("--url", help="instance base URL; prints a ready-to-open login link")
    ap.add_argument("--key", default=os.environ.get("SHOWWISE_SUPPORT_KEY",
                    os.path.expanduser("~/.showwise/support_ed25519.key")))
    a = ap.parse_args()
    if not 1 <= a.minutes <= 30:
        ap.error("--minutes must be 1-30")
    tok = mint_token(load_key(a.key), a.instance, a.operator, a.scope, a.minutes)
    print(f"{a.url.rstrip('/')}/support/login?token={tok}" if a.url else tok)
