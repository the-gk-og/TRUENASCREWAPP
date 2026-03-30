# ShowWise Feature Updates - Archiving & Multiple Grouping Support

## Overview

This update adds several new features to ShowWise for better event management:

1. **Archive Support** - Archive stageplans and picklists after events end
2. **CSV Import/Export** - Import/export schedules, run lists, and picklists as CSV files with templates
3. **Multiple Picklists** - Create and manage multiple picklists per event (e.g., for different stages)
4. **Multiple Stage Plans** - Create and manage collections of stage plans per event

## Features

### 1. Archive Support

#### Auto-Archive After Event Ends
When an event ends, you can automatically archive all associated stageplans and picklists:

**Endpoint**: `POST /events/<event_id>/auto-archive`

This will archive all stage plans and picklists for the completed event.

#### Manual Archive/Unarchive

**Archive a Picklist**:
```
PUT /events/picklists/<picklist_id>/archive
```

**Archive a Stage Plan**:
```
PUT /events/stageplans/<plan_id>/archive
```

**Archive a Stage Collection**:
```
PUT /stage-collections/<collection_id>/archive
```

Archived items are hidden from view by default but can be recovered by toggling archival status again.

### 2. CSV Import/Export

#### Download CSV Templates

Available templates for import:
- **Event Schedule** - title, scheduled_time, description
- **Cast Schedule** - title, scheduled_time, description
- **Crew Run List** - order, title, description, duration, cue type, notes
- **Cast Run List** - order, title, description, duration, type, cast involved, notes
- **Picklist** - item name, quantity, equipment ID

**Endpoint**: `GET /events/download-csv-template/<template_type>`

Example:
```bash
curl http://yourserver/events/download-csv-template/event_schedule
```

#### Export Event Data

**Export Event Schedule**:
```
GET /events/<event_id>/export-csv/event_schedule
```

**Export Cast Schedule**:
```
GET /events/<event_id>/export-csv/cast_schedule
```

**Export Crew Run List**:
```
GET /events/<event_id>/export-csv/crew_run_list
```

**Export Cast Run List**:
```
GET /events/<event_id>/export-csv/cast_run_list
```

#### Import Event Data

**Endpoint**: `POST /events/<event_id>/import-csv`

**Parameters**:
- `file` (required) - CSV file to import
- `import_type` (required) - Type of data to import
- `picklist_id` (optional) - For picklist imports, the target picklist ID

**Example**:
```bash
curl -X POST http://yourserver/events/123/import-csv \
  -F "file=@event_schedule.csv" \
  -F "import_type=event_schedule"
```

### 3. Multiple Picklists

#### Create a New Picklist

**Endpoint**: `POST /picklists/create`

**Parameters**:
- `event_id` (required) - The event this picklist belongs to
- `name` (required) - Name for the picklist (e.g., "Stage 1 Equipment", "Props")

**Response**:
```json
{
  "success": true,
  "id": 5,
  "name": "Stage 1 Equipment"
}
```

#### Add Items to a Picklist

**Endpoint**: `POST /picklist/add`

**Parameters**:
- `event_id` (required) - The event ID
- `picklist_id` (required) - The target picklist ID
- `item_name` (required) - Name of the item
- `quantity` (optional) - Quantity needed (default: 1)
- `equipment_id` (optional) - Link to existing equipment

#### View Picklist Items

**Endpoint**: `GET /picklists/<picklist_id>/items`

**Response**:
```json
{
  "success": true,
  "picklist": {
    "id": 5,
    "name": "Stage 1 Equipment",
    "event_id": 123,
    "created_by": "username"
  },
  "items": [
    {
      "id": 1,
      "item_name": "Microphone",
      "quantity": 2,
      "is_checked": false,
      "equipment_id": 42
    }
  ]
}
```

#### Archive a Picklist

**Endpoint**: `PUT /picklists/<picklist_id>/archive`

Archives the picklist and all its items.

#### Delete a Picklist

**Endpoint**: `DELETE /picklists/<picklist_id>/delete`

### 4. Multiple Stage Plans (Collections)

#### Create a Stage Plan Collection

**Endpoint**: `POST /stage-collections/create`

**Parameters**:
- `event_id` (required) - The event this collection belongs to
- `name` (required) - Name for the collection (e.g., "Act 1 Stage Plans", "Multi-Stage Setup")

**Response**:
```json
{
  "success": true,
  "id": 3,
  "name": "Act 1 Stage Plans"
}
```

#### Upload Stage Plan to Collection

When uploading a stage plan, you can now specify a collection:

**Endpoint**: `POST /stageplans/upload`

**Parameters**:
- `file` (required) - The stage plan file
- `event_id` (required) - The event ID
- `collection_id` (optional) - Add to a collection
- `title` (optional) - Name for the plan

#### Add Existing Plan to Collection

**Endpoint**: `POST /stage-collections/<collection_id>/add-plan`

**Parameters**:
- `plan_id` (required) - The stage plan to add

#### View Collection Plans

**Endpoint**: `GET /stage-collections/<collection_id>/plans`

**Response**:
```json
{
  "success": true,
  "collection": {
    "id": 3,
    "name": "Act 1 Stage Plans",
    "event_id": 123,
    "created_by": "username"
  },
  "plans": [
    {
      "id": 1,
      "title": "Scene 1 Layout",
      "filename": "scene1_layout.pdf",
      "uploaded_by": "username",
      "created_at": "2024-03-27T10:00:00"
    }
  ]
}
```

#### Archive a Collection

**Endpoint**: `PUT /stage-collections/<collection_id>/archive`

Archives the collection and all its plans.

#### Delete a Collection

**Endpoint**: `DELETE /stage-collections/<collection_id>/delete`

## Database Migration

To apply these changes to an existing database, run:

```bash
cd Migration_scripts
python migrate_archive_and_groups.py
```

This will:
1. Add `is_archived` column to PickListItem and StagePlan tables
2. Add `picklist_id` column to PickListItem table
3. Add `collection_id` column to StagePlan table
4. Create the new Picklist and StagePlanCollection tables

## CSV Format Examples

### Event Schedule Template
```csv
Title,Scheduled Time,Description
Morning Briefing,2024-03-27T09:00:00,Technical check
Sound Check,2024-03-27T10:00:00,Audio setup and testing
```

### Crew Run List Template
```csv
Order,Title,Description,Duration,Cue Type,Notes
1,Scene 1 Setup,Prepare lighting and sound,10 mins,GO,All crew present
2,Scene 1 Run,Execute scene 1,15 mins,STANDBY,Watch for cues
```

### Picklist Template
```csv
Item Name,Quantity,Equipment ID
Microphone,2,42
Speaker,1,43
Cables,10,
```

## Backward Compatibility

All changes are backward compatible. Existing picklists and stage plans without a group assignment will continue to work as before. The grouping features are optional enhancements.

## Model Relationships

### New Models

#### Picklist
- `id` - Primary key
- `name` - Name of the picklist group
- `event_id` - Foreign key to Event
- `created_by` - Username of creator
- `created_at` - Timestamp
- `is_archived` - Archive status
- `items` - Relationship to PickListItem

#### StagePlanCollection
- `id` - Primary key
- `name` - Name of the collection
- `event_id` - Foreign key to Event
- `created_by` - Username of creator
- `created_at` - Timestamp
- `is_archived` - Archive status
- `plans` - Relationship to StagePlan

### Modified Models

#### PickListItem
- Added: `picklist_id` (Optional FK to Picklist)
- Added: `is_archived` (Boolean, default False)

#### StagePlan
- Added: `collection_id` (Optional FK to StagePlanCollection)
- Added: `is_archived` (Boolean, default False)
