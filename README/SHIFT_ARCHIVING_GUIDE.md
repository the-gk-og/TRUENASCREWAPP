# Shift Archiving Feature

## Overview

Shifts now support automatic archiving when they end, helping keep your shift management interface clean and organized. Completed shifts are hidden by default but can be recovered at any time.

## Features

### 1. Auto-Archive Completed Shifts

Shifts are automatically archived when their end time passes. This can happen:
- Manually via API call
- Automatically through background processes (recommended for scheduled task)

#### Auto-Archive All Completed Shifts

**Endpoint**: `POST /shifts/auto-archive`

Archives all shifts across all events whose end time has passed. Requires admin access.

**Response**:
```json
{
  "success": true,
  "archived_count": 5,
  "message": "Archived 5 completed shift(s)"
}
```

#### Auto-Archive Completed Shifts for a Specific Event

**Endpoint**: `POST /shifts/event/<event_id>/auto-archive`

Archives all completed shifts belonging to a specific event. Requires admin access.

**Parameters**:
- `event_id` (required) - The event ID

**Response**:
```json
{
  "success": true,
  "archived_count": 3,
  "message": "Archived 3 completed shift(s) for this event"
}
```

### 2. Manual Archive/Unarchive

#### Archive or Unarchive a Shift

**Endpoint**: `PUT /shifts/<shift_id>/archive`

Toggles the archive status of a shift. Requires admin access.

**Response**:
```json
{
  "success": true,
  "is_archived": true
}
```

Call again to unarchive:
```json
{
  "success": true,
  "is_archived": false
}
```

### 3. Query Archived Shifts

#### Get Active (Non-Archived) Shifts (Default)

**Endpoint**: `GET /api/shifts`

By default, returns only active (non-archived) shifts.

**Parameters**:
- `event_id` (optional) - Filter by event
- `include_archived` (optional) - Set to `true` to include archived shifts

**Response**:
```json
[
  {
    "id": 1,
    "title": "Morning Setup",
    "shift_date": "2024-03-27T08:00:00",
    "shift_end_date": "2024-03-27T10:00:00",
    "is_archived": false,
    "is_open": true,
    "assignments_count": 2,
    ...
  }
]
```

#### Get Archived Shifts Only

**Endpoint**: `GET /api/shifts/archived`

Returns all archived shifts. Requires admin access.

**Parameters**:
- `event_id` (optional) - Filter archived shifts by event

**Response**:
```json
[
  {
    "id": 5,
    "title": "Completed: Evening Teardown",
    "shift_date": "2024-03-26T18:00:00",
    "shift_end_date": "2024-03-26T20:00:00",
    "is_archived": true,
    ...
  }
]
```

### 4. Shift Management Page

The shift management page (`/shifts/management`) automatically shows only active shifts, keeping the interface focused on current and upcoming work.

**To view archived shifts manually**:
1. Use the API endpoint `/api/shifts/archived` 
2. Or use the `include_archived=true` parameter with the regular shifts endpoint

## User Experience Benefits

- **Cleaner Interface**: Completed shifts don't clutter the management page
- **Easy Recovery**: Archive is not deletion - shifts can be restored
- **Audit Trail**: Archived shifts preserve all assignment history
- **Historical View**: Admin can review past shifts without seeing active ones

## Database Migration

To enable shift archiving on your existing database, run:

```bash
cd Migration_scripts
python migrate_shift_archiving.py
```

This will add the `is_archived` column to the Shift table.

## Model Changes

### Shift Model

**New Column**:
- `is_archived` (Boolean, default: False) - Marks whether a shift is archived

**Updated Queries**:
- Default queries now exclude archived shifts
- Use `include_archived=true` parameter to include them
- Use dedicated `/api/shifts/archived` endpoint for archived-only view

## Best Practices

1. **Automatic Archiving**: Set up a scheduled task to call `POST /shifts/auto-archive` daily
   - This keeps your live shifts list clean automatically
   - Suggested: Run at midnight or early morning

2. **Event-Based Archiving**: After an event ends, call `POST /shifts/event/<event_id>/auto-archive`
   - Ensures all shifts from completed events are archived

3. **Manual Override**: Use `PUT /shifts/<shift_id>/archive` to manually archive/unarchive
   - Useful if a shift needs to be marked complete early
   - Or if an archived shift needs to be reopened

4. **Viewing History**: Use `/api/shifts/archived` to review completed shifts
   - Check assignments and notes from past events
   - Maintain historical records

## Comparison with Other Features

| Feature | Archiving | Deletion |
|---------|-----------|----------|
| Data retained | ✅ Yes | ❌ No |
| Recoverable | ✅ Yes | ❌ No |
| History preserved | ✅ Yes | ❌ No |
| Reduces clutter | ✅ Yes | ✅ Yes |
| Recommended use | Active/completed tracking | Never (data loss risk) |

## API Summary

| Operation | Endpoint | Method | Access |
|-----------|----------|--------|--------|
| Get active shifts | `/api/shifts` | GET | Crew |
| Get archived shifts | `/api/shifts/archived` | GET | Admin |
| Archive a shift | `/shifts/<id>/archive` | PUT | Admin |
| Auto-archive all | `/shifts/auto-archive` | POST | Admin |
| Auto-archive by event | `/shifts/event/<id>/auto-archive` | POST | Admin |
