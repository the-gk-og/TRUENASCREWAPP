# Pick List & Equipment Linking Guide

The pick list now integrates with your equipment database to provide complete item details!

## What's New

### Dual-Mode Item Adding

Pick lists now have **two ways to add items**:

#### 1. From Equipment (Recommended)
- Select from your existing equipment list
- Automatically includes:
  - ✅ Item name
  - ✅ Storage location
  - ✅ Item category
  - ✅ Barcode number
  - ✅ Any notes
- Set quantity needed
- One click to add

#### 2. Manual Entry
- Add custom items not in equipment list
- Useful for:
  - Consumables (batteries, tape, etc.)
  - Rentals
  - Items to purchase
  - Temporary items
- Simple name and quantity

## Features

### Enhanced Pick List Display

Each pick list item now shows:

**Basic Information:**
- ✅ Item name
- ✅ Quantity needed
- ✅ Added by (who added it)
- ✅ Check status (gathered or not)

**Equipment Details (if linked):**
- 📍 Storage location (where to find it)
- 🏷️ Category (type of equipment)
- 📦 Barcode (for scanning)
- 📝 Notes (special info)

**Visual Design:**
- Yellow highlighted box for equipment details
- Color-coded status
- Progress tracking
- Easy delete button

### Real-World Example

**From Equipment:**
```
Item: Spotlight A
Qty: 2
Location: Equipment Room, Shelf 1
Category: Lighting
Barcode: PROD-001
Notes: 500W, working condition
```

**Manual Entry:**
```
Item: Batteries (AA)
Qty: 50
Location: (none)
Category: (none)
Notes: (none)
```

## How to Use

### Creating a Pick List

1. **Go to Pick List page**
   - Click "📋 Pick List" in navigation

2. **Select event (optional)**
   - Dropdown to filter by event
   - Or use General list

3. **Click "+ Add Item"**
   - Modal opens with two tabs

### Adding From Equipment

1. **Click "From Equipment" tab**
2. **Select equipment** from dropdown
   - Shows location in dropdown
   - Makes finding items easy
3. **Set quantity** needed
4. **Select event** (optional)
5. **Click "Add Equipment"**

**Result:**
- Item added to list
- Location shown
- Details visible
- Ready to gather

### Adding Manual Item

1. **Click "Manual Entry" tab**
2. **Enter item name** (required)
3. **Set quantity** (default 1)
4. **Select event** (optional)
5. **Click "Add Item"**

**Result:**
- Item added to list
- No equipment details (manual only)
- Good for consumables

## Gathering Items

### On Mobile

1. **See each item clearly**
   - Large item name
   - Quantity displayed
   - Location in yellow box
   - Tap checkbox to gather

2. **Use barcode if linked**
   - Equipment page
   - Scan barcode from pick list
   - Confirms you have right item

3. **Check off as you go**
   - Tap checkbox
   - Item grayed out
   - Progress bar updates

### Workflow

```
1. See item in list: "Spotlight A"
2. See location: "Equipment Room, Shelf 1"
3. Go find it
4. Scan barcode to confirm: PROD-001
5. Check off in pick list ✓
6. Repeat for next item
```

## Database Schema

### PickListItem Model

**New fields added:**
```python
equipment_id: Integer (Foreign Key to Equipment)
equipment: Relationship (linked equipment object)
```

**This allows:**
- Link each pick list item to equipment
- Pull equipment details automatically
- Keep data synchronized
- Query efficiently

## Admin Benefits

### Better Inventory Management

As an admin you can:

1. **Maintain master equipment list**
   - Add all equipment
   - Update locations
   - Set categories
   - Add notes/barcodes

2. **Pick lists stay current**
   - Equipment details auto-populate
   - If location changes, updates everywhere
   - No manual updates needed
   - Single source of truth

3. **Track what's needed**
   - See what equipment per event
   - Know total quantities needed
   - Manage inventory usage
   - Plan for repairs/maintenance

## Crew Member Experience

### Before (Manual Entry Only)
```
Pick List:
- Spotlight
- Microphone
- Camera

Problem: Where is it? What do I grab?
```

### After (Equipment Linked)
```
Pick List:
- Spotlight A
  Location: Equipment Room, Shelf 1
  Category: Lighting
  Barcode: PROD-001

Result: Crew knows exactly what to grab
```

## Data Sync Examples

### Scenario 1: Update Equipment Location

**What happens:**
1. Admin updates equipment location
   - Equipment Room → Storage Room B
2. Next time pick list shown
3. **Location updates automatically**
4. Crew sees new location
5. No manual updates needed

### Scenario 2: Add Barcode to Equipment

**What happens:**
1. Admin adds barcode to equipment
2. Pick list items linked to that equipment
3. **Barcode appears in pick list**
4. Crew can scan to verify
5. Much faster gathering

### Scenario 3: Add Equipment Notes

**What happens:**
1. Admin adds notes: "Needs bulb replacement"
2. Pick lists show the note
3. **Crew alerted immediately**
4. Can check before using
5. Better equipment care

## API Changes

### Add Pick List Item

**Request:**
```json
{
  "equipment_id": 5,
  "quantity": 2,
  "event_id": null
}
```

**OR**

```json
{
  "item_name": "Batteries",
  "quantity": 50,
  "event_id": 1
}
```

**Response:**
```json
{
  "success": true,
  "id": 12,
  "item": {
    "item_name": "Spotlight A",
    "quantity": 2,
    "equipment": {
      "location": "Equipment Room, Shelf 1",
      "category": "Lighting",
      "barcode": "PROD-001"
    }
  }
}
```

## Queries & Features

### Find All Items for Event

```python
items = PickListItem.query.filter_by(event_id=5).all()

# Access equipment details:
for item in items:
    if item.equipment:
        print(f"{item.item_name}")
        print(f"Location: {item.equipment.location}")
        print(f"Barcode: {item.equipment.barcode}")
```

### Track Equipment Usage

```python
# Which events use this equipment?
equipment = Equipment.query.get(5)
for pick_list_item in equipment.pick_list_items:
    event = pick_list_item.event
    print(f"Used in: {event.title}")
```

### Missing Equipment Details

```python
# Manual items (no equipment link)
manual_items = PickListItem.query.filter_by(equipment_id=None).all()

# Equipment items (linked)
linked_items = PickListItem.query.filter(
    PickListItem.equipment_id.isnot(None)
).all()
```

## Best Practices

### For Admins

✅ **Do This:**
- Keep equipment list updated
- Add locations to all equipment
- Use clear, descriptive names
- Add barcodes where possible
- Update notes for issues

❌ **Avoid:**
- Deleting active equipment (archive instead)
- Changing equipment names frequently
- Missing location information
- Duplicate equipment entries

### For Crew

✅ **Do This:**
- Check location in pick list first
- Use barcode scanning to verify
- Mark items as gathered
- Note any issues
- Return equipment to storage

❌ **Avoid:**
- Moving equipment without updating location
- Ignoring equipment notes
- Skipping barcode verification
- Taking items without checking list

## Examples

### Example 1: School Play Production

**Equipment Setup:**
```
- Spotlight A (Location: Stage Left Rack)
- Spotlight B (Location: Stage Right Rack)  
- Microphone 1 (Location: Audio Cabinet)
- Audio Cable (Location: Cable Bin)
```

**Pick List for Opening Night:**
```
□ Spotlight A - Qty: 1 - Location: Stage Left Rack
  - Found in: Equipment Room, Shelf 1
  - Barcode: PROD-001
  
□ Spotlight B - Qty: 1 - Location: Stage Right Rack
  - Found in: Equipment Room, Shelf 1
  - Barcode: PROD-002
  
□ Microphone 1 - Qty: 1 - Location: Audio Cabinet
  - Found in: Equipment Room, Cabinet 2
  - Barcode: PROD-005
  - Note: Test battery first!
```

### Example 2: Mixed Items

```
□ Camera Canon - Location: Equipment Room, Shelf 2
  - Barcode: PROD-010
  
□ Batteries (AA) - (Manual entry)
  - Qty: 48
  - No location (consumable)
  
□ Gaff Tape (2in) - (Manual entry)
  - Qty: 3 rolls
  - For quick fixes
```

## Troubleshooting

### Equipment Not Showing in Dropdown

**Problem:** Can't find equipment to add
- **Solution:** Make sure equipment is added first
  - Go to Equipment page
  - Add missing items
  - Then try pick list again

### Deleted Equipment Still Shows

**Problem:** Equipment removed but pick list items remain
- **Solution:** This is intentional
  - Pick list items stay
  - Details preserved even if equipment deleted
  - Archive equipment instead of deleting

### Location Not Showing

**Problem:** Equipment selected but no location visible
- **Solution:** Admin needs to add location
  - Equipment page
  - Edit equipment
  - Add storage location
  - Save

### Barcode Not Displaying

**Problem:** Equipment has barcode but not in pick list
- **Solution:** Add barcode to equipment first
  - Equipment page
  - Edit equipment
  - Add barcode
  - Save
  - Pick list updates automatically

## Future Enhancements

Potential additions:

- 📊 Equipment usage statistics
- 🔄 Automatic reordering of items
- 🎯 Smart suggestions based on event type
- 📈 Equipment checkout/check-in system
- 🚨 Equipment condition tracking
- 💾 Pick list templates by event type
- 📤 Export pick list to PDF/Excel
- 🔔 Notifications when items needed

## Summary

✅ **Pick lists now linked to equipment**
✅ **Automatic details included**
✅ **Manual entry still available**
✅ **Mobile-friendly display**
✅ **Real-time sync**
✅ **Better crew experience**
✅ **Improved inventory management**

**Pick lists are now smarter and more powerful!** 📋