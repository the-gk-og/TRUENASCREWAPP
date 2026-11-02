#!/usr/bin/env python3
"""Generate the support signing keypair. Run once, on YOUR machine."""
import base64, os, sys
from cryptography.hazmat.primitives import serialization as s
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

path = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/.showwise/support_ed25519.key")
if os.path.exists(path):
    sys.exit(f"Refusing to overwrite {path}")
os.makedirs(os.path.dirname(path), exist_ok=True)
priv = Ed25519PrivateKey.generate()
raw = priv.private_bytes(s.Encoding.Raw, s.PrivateFormat.Raw, s.NoEncryption())
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as f:
    f.write(base64.urlsafe_b64encode(raw).decode() + "\n")
pub = priv.public_key().public_bytes(s.Encoding.Raw, s.PublicFormat.Raw)
print(f"Private key saved to {path} (keep it off every server, back it up)")
print("Put this in each instance's env:\n")
print("SUPPORT_PUBLIC_KEY=" + base64.urlsafe_b64encode(pub).decode())
print("SUPPORT_INSTANCE_ID=<unique-name-for-that-deployment>")
