"""
Test ShowWise Backend Integration

Run this to verify everything works.
"""

import os
from backend_integration import ShowWiseBackend
from dotenv import load_dotenv

load_dotenv()

# Initialize client
backend = ShowWiseBackend(
    backend_url=os.getenv('BACKEND_URL', 'http://localhost:5001'),
    api_key=os.getenv('BACKEND_API_KEY', ''),
    org_slug=os.getenv('ORG_SLUG', 'test')
)

print("="*50)
print("  ShowWise Backend Integration Test")
print("="*50)

# Test 1: Get Organization
print("\n1. Testing Organization API...")
org = backend.get_organization()
if org:
    print(f"   ✓ Organization: {org.get('name')}")
    print(f"   ✓ URL: {org.get('url')}")
else:
    print("   ✗ Failed to get organization")

# Test 2: Logging
print("\n2. Testing Logging API...")
if backend.log_info("Test log from integration test", "system"):
    print("   ✓ Log sent successfully")
else:
    print("   ✗ Failed to send log")

# Test 3: Heartbeat
print("\n3. Testing Uptime API...")
if backend.send_heartbeat("online", {"test": True}):
    print("   ✓ Heartbeat sent successfully")
else:
    print("   ✗ Failed to send heartbeat")

# Test 4: Kill Switch
print("\n4. Testing Kill Switch API...")
enabled, reason = backend.check_kill_switch()
print(f"   Kill Switch: {'ENABLED' if enabled else 'Disabled'}")
if enabled:
    print(f"   Reason: {reason}")

# Test 5: Chat
print("\n5. Testing Chat API...")
msg_id = backend.send_chat_message("Test User", "This is a test message", "test@example.com")
if msg_id:
    print(f"   ✓ Message sent: #{msg_id}")
else:
    print("   ✗ Failed to send message")

print("\n" + "="*50)
print("  Test Complete!")
print("="*50)
