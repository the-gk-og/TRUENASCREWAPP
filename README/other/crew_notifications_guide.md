# Crew Notifications System - Complete Guide

## How It Works

The Production Crew Management System now has an intelligent notification system that only sends emails to crew members who are actually assigned to events.

### Key Features

1. **Selective Notifications** - Only assigned crew members get notified
2. **Account Linking** - Crew accounts are linked through the user system
3. **Email Integration** - Automatic notifications when assigned
4. **Resend Capability** - Manually resend notifications if needed
5. **Status Tracking** - See who was notified and who wasn't

## Setup Process

### Step 1: Create User Accounts

1. Go to **Admin Panel** → **User Management**
2. Click **+ Add User**
3. Enter:
   - Username (crew member's name)
   - Email address (for notifications)
   - Password (they can change after login)
   - Admin privileges (optional, only for admins)
4. Click **Create User**

**Example:**
- Username: `john_smith`
- Email: `john.smith@school.edu`
- Password: `temporary_password_123`

### Step 2: Add Crew to Events

1. Go to **Calendar** → Click on an event
2. Click **+ Add Crew**
3. A dropdown appears with all registered users
4. **Select a crew member** - Shows their email address
5. Enter their **Role** (e.g., "Stage Manager", "Lighting Operator")
6. Click **Add to Crew**

### Step 3: Automatic Notification

When you add a crew member to an event:
- ✅ If they have an email → **Notification sent automatically**
- ❌ If no email → **No notification** (but they're still assigned)

The crew member receives an email with:
- Event name
- Date and time
- Location
- Their assigned role
- Link to the system

## Status Indicators

On the event detail page, you'll see the status of each crew member:

### ✅ Notified (Green)
- Crew member has an email address
- Notification was sent when they were assigned
- Shows: "Notified"

### ⚠️ No Email (Red)
- Crew member doesn't have an email address
- No notification sent
- Shows: "No Email"

## Resending Notifications

Sometimes you need to resend a notification (e.g., they didn't see it, you made changes).

**How to resend:**

1. Go to the event
2. Find the crew member in the list
3. Click the **🔄 Resend** button next to their name
4. Confirm
5. Email sent again

This only appears for crew members with email addresses.

## Email Content

### Crew members receive:

```
Subject: 🎭 You're assigned to: [Event Name]

Hello [Username],

You have been assigned to an upcoming production event!

📋 Event Details:
  • Event: [Event Name]
  • Date & Time: [Full Date & Time]
  • Location: [Location]
  • Your Role: [Their Role]

📝 Description: [Event Description]

Please log in to the Production Crew Management System to view:
  • Pick lists for items to gather
  • Stage plans for setup
  • Other crew members assigned to this event
  • Event details and updates

Let me know if you have any questions!

Best regards,
Production Crew System
```

## Linking Crew Accounts to Events

### Traditional Way (Per Event)

1. Go to **Calendar**
2. Click on event
3. Click **+ Add Crew**
4. Add individual crew members

### Bulk Assignment (Multiple Events)

1. Create all user accounts first (Admin panel)
2. Add them to events one by one
3. Each gets notified automatically

### Pre-Assigning Crew

1. Before the event is created, have all crew accounts ready
2. Create the event
3. Add all crew members to it
4. All get notified at once

## Best Practices

### ✅ Do This

- ✅ Create all crew member accounts when they join the team