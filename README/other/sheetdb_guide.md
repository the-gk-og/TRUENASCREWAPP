# Google Sheets Integration with SheetDB

Connect your Google Sheet inventory directly to the Production Crew system using SheetDB.

## What is SheetDB?

SheetDB provides a free API to read data from Google Sheets. No coding required!

## Step 1: Create Your Google Sheet

1. Go to [Google Sheets](https://sheets.google.com)
2. Create a new spreadsheet
3. Name it "Production Crew Inventory" (or your preferred name)
4. Add these column headers:
   - **Barcode** (unique ID like PROD-001)
   - **Name** (equipment name)
   - **Category** (Lighting, Audio, Video, etc.)
   - **Location** (Storage Room A, Shelf 2, etc.)
   - **Notes** (optional details)

### Example Data:

| Barcode | Name | Category | Location | Notes |
|---------|------|----------|----------|-------|
| PROD-001 | Spotlight A | Lighting | Equipment Room, Shelf 1 | 500W |
| PROD-002 | Microphone 1 | Audio | Equipment Room, Shelf 2 | Condenser |
| PROD-003 | Camera Canon | Video | Storage Room B, Shelf 1 | 4K capable |

## Step 2: Get Your Sheet ID

1. Click **Share** on your Google Sheet
2. Set to "Viewer" access for anyone with link
3. Copy the sheet URL: `https://docs.google.com/spreadsheets/d/SHEET_ID/edit`
4. Extract the SHEET_ID (the long string between `/d/` and `/edit`)

Example: `https://docs.google.com/spreadsheets/d/1a2b3c4d5e6f7g8h9i0j/edit`
Your SHEET_ID is: `1a2b3c4d5e6f7g8h9i0j`

## Step 3: Convert Sheet to SheetDB

1. Go to [SheetDB](https://sheetdb.io)
2. Click **Create API**
3. Paste your Google Sheet URL
4. Click **Create**
5. You'll get a SheetDB ID that looks like: `abcd1234efgh5678`

## Step 4: Import in Production Crew

1. Login to your Production Crew system
2. Go to **Admin** → **Import Equipment**
3. Click **Import from SheetDB**
4. Paste your SheetDB ID
5. Click **Import from Sheet**

That's it! Your equipment is now in the system.

## Updating Your Inventory

### Method 1: Edit in Google Sheet (Automatic)
1. Edit your Google Sheet
2. Next time you import, new items are added

### Method 2: Edit in Production Crew
1. Go to Equipment
2. Edit items directly
3. Changes are local only (not synced back to Sheet)

## Tips & Tricks

### Multiple Sheets

If you have multiple sheets in one document:
- SheetDB uses "Sheet1" by default
- To use a different sheet, edit the URL in SheetDB settings

### Keeping Things in Sync

**Best Practice**: Edit in Google Sheet, import regularly
- Google Sheet is your "source of truth"
- Import new items weekly or monthly
- Production Crew UI for quick lookups

### Column Names

SheetDB looks for these (case-insensitive):
- `barcode` or `Barcode`
- `name` or `Name`
- `category` or `Category`
- `location` or `Location`
- `notes` or `Notes`

### Duplicate Barcodes

The system automatically skips items with barcodes that already exist.
- Safe to re-import
- Won't create duplicates

## Sharing Your Sheet

### With Your Crew

1. Share Google Sheet link with team
2. They can view live data
3. You maintain the source

### Collaboration

Multiple people can edit the sheet:
1. Share with "Editor" access
2. All changes sync in real-time
3. Import regularly to Production Crew

## Troubleshooting

### "Invalid SheetDB ID"
- Check your SheetDB ID is correct
- Make sure Google Sheet is shared publicly

### "No data found"
- Verify headers: Barcode, Name, Category, Location, Notes
- Check that data is in the sheet
- Refresh SheetDB: Delete and recreate API

### Import shows 0 items
- Usually means all items already exist (duplicates skipped)
- Check Admin panel to see current equipment

### SheetDB Service Down
- Service is usually very reliable
- As backup, use CSV import instead

## Alternative: CSV Import

If SheetDB has issues:

1. Export Google Sheet as CSV
2. Admin → **Import Equipment**
3. Click **Import from CSV**
4. Select the CSV file
5. Click Import

## Free Tier Limits

SheetDB free tier:
- ✅ Unlimited reads
- ✅ Unlimited API calls
- ✅ Up to 10,000 cells
- Perfect for most production crews

## Security Notes

- ⚠️ Anyone with the Google Sheet link can see your inventory
- For sensitive equipment, use "Viewer" access only
- Don't share with public
- SheetDB doesn't store data, just reads from Google

## Getting Help

- **SheetDB Support**: [sheetdb.io/help](https://sheetdb.io)
- **Google Sheets Help**: [support.google.com/sheets](https://support.google.com/sheets)
- Check Production Crew admin logs for error details

## Example Setup

Complete walkthrough:

1. **Create Sheet** (5 min)
   - Go to Google Sheets
   - Add headers
   - Add 5-10 equipment items

2. **Setup SheetDB** (2 min)
   - Open SheetDB
   - Connect Google Sheet
   - Copy SheetDB ID

3. **Import to Production Crew** (1 min)
   - Go to Admin
   - Paste SheetDB ID
   - Click Import

**Total time**: ~8 minutes! 🚀

## Next Steps

- Review imported equipment in Equipment page
- Add more items to Google Sheet as needed
- Re-import whenever you update the sheet
- Use barcode scanning to find locations instantly!