# Web Push notifications

People turn notifications on per device in **Settings → Notifications**, and choose which kinds they
want (this applies to all their devices; email is unaffected). Tapping a notification opens the page it's about.

| Kind | When | Opens |
|---|---|---|
| New shifts | Someone gives you a shift | My schedule |
| Shift reminders | Hourly job, shifts starting in the next 24 h (same admin switch as reminder emails) | My schedule |
| Declined shifts | A crew member declines (goes to the people chosen in Admin → Notifications) | The event |
| Added to an event | You're added to an event's crew | The event |

Push goes out even when email isn't set up, or for people with no email address.

## Setup

1. `pip install -r requirements.txt` (adds `pywebpush`).
2. VAPID keys. Optional, but **recommended for production**:
   ```
   VAPID_PUBLIC_KEY=<base64url uncompressed P-256 public key, 87 chars>
   VAPID_PRIVATE_KEY=<base64url raw 32-byte private key, 43 chars>
   VAPID_SUBJECT=mailto:you@your-venue.org   # push services use this to contact you
   ```
   If they're not set, a key pair is generated on first use and stored in the database
   (`app_setting` row `push.vapid`), so it survives restarts. **Don't change or delete the keys
   once people have subscribed**: every existing subscription stops working and people must turn
   notifications on again. To make a pair yourself:
   ```
   python -c "from services.push_service import _b64; from cryptography.hazmat.primitives.asymmetric import ec; from cryptography.hazmat.primitives import serialization as s; k=ec.generate_private_key(ec.SECP256R1()); print('VAPID_PRIVATE_KEY='+_b64(k.private_numbers().private_value.to_bytes(32,'big'))); print('VAPID_PUBLIC_KEY='+_b64(k.public_key().public_bytes(s.Encoding.X962,s.PublicFormat.UncompressedPoint)))"
   ```
3. The site must be served over **HTTPS** (or `localhost`) for browsers to allow push.
4. iPhone/iPad: works only once ShowWise is added to the Home Screen (iOS 16.4+) and opened from there.
   The settings page says so.

## How it works

- `services/push_service.py`: keys, per-person kinds (`push_preference`), sending. Subscriptions the push
  service reports as gone (404/410) are deleted. All network traffic goes through `_webpush`, which tests replace.
- `routes/pwa.py`: `/push/key`, `/push/subscribe`, `/push/unsubscribe`, `/push/preferences`, `/push/test`.
- `static/js/service-worker.js`: shows the notification and opens/focuses the page on tap. Logging out
  unsubscribes that device, so the next person on a shared phone doesn't get the previous person's notifications.
- New tables `push_subscription` and `push_preference` are created automatically (no numbered migration).
