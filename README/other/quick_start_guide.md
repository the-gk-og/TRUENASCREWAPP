# Quick Start Guide

Get your Production Crew Management System up and running in 5 minutes!

## 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

## 2. Create Required Folders

```bash
mkdir templates uploads
```

## 3. Save All Template Files

Place these HTML files in the `templates/` folder:
- `base.html`
- `login.html`
- `dashboard.html`
- `equipment.html`
- `picklist.html`
- `stageplans.html`
- `calendar.html`
- `event_detail.html`
- `admin.html`

## 4. Run the Application

```bash
python app.py
```

You should see:
```
Default admin user created: username='admin', password='admin123'
 * Running on http://0.0.0.0:5000
```

## 5. Login and Get Started

1. Open browser: `http://localhost:5000`
2. Login with:
   - Username: `admin`
   - Password: `admin123`
3. **IMPORTANT**: Change this password immediately!

## First Steps After Login

### 1. Add Users
- Go to **Admin** panel
- Click **+ Add User**
- Add crew members with their email addresses (optional but needed for notifications)
- Regular users can view/edit, admins can delete

### 2. Add Equipment
- Go to **Equipment** page
- Click **+ Add Equipment**
- Enter:
  - Barcode (e.g., `PROD-001`)
  - Name (e.g., `Spotlight A`)
  - Category (e.g., `Lighting`)
  - Storage Location (e.g., `Equipment Room, Shelf 2`)

### 3. Create an Event
- Go to **Calendar** page
- Click **+ Add Event**
- Fill in event details
- Click **Create Event**

### 4. Assign Crew to Event
- Click on the event to view details
- Click **+ Add Crew**
- Select crew member and their role
- If they have an email, they'll be notified automatically!

### 5. Create Pick List
- Go to **Pick List** page
- Select the event from dropdown
- Click **+ Add Item**
- Add all items needed for the event
- Crew members can check items off as they're gathered

### 6. Upload Stage Plan
- Go to **Stage Plans** page
- Click **+ Upload Stage Plan**
- Select your event
- Upload an image or PDF
- Share the link with your crew!

## Using Camera Barcode Scanning

### On Desktop:
1. Go to **Equipment** page
2. Click **📱 Scan Barcode**
3. Click **📷 Start Camera**
4. Allow camera access when prompted
5. Point camera at barcode
6. System automatically detects and shows location!

### On Mobile:
- Same process, but works better with rear camera
- Hold phone steady about 6-12 inches from barcode
- Ensure good lighting
- Fallback: Manual entry always available

## Network Access (School-Wide)

### Find Your IP Address:

**Windows:**
```cmd
ipconfig
```
Look for "IPv4 Address" (e.g., `192.168.1.100`)

**Mac/Linux:**
```bash
ifconfig
```
or
```bash
ip addr
```

### Access from Other Devices:
```
http://YOUR_IP:5000
```
Example: `http://192.168.1.100:5000`

## Email Notifications (Optional)

1. See `EMAIL_SETUP.md` for detailed instructions
2. Create `.env` file:
```
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-app-password
```
3. Restart the app
4. Add email addresses to user accounts
5. Notifications sent automatically when crew assigned!

## Common Tasks

### Scan Equipment Location
1. Equipment → Scan Barcode
2. Use camera or type barcode
3. View location instantly

### Check Off Pick List Items
1. Pick List → Select event
2. Click checkboxes as items are gathered
3. Everyone sees real-time updates

### View Stage Plan
1. Stage Plans → Select event
2. Click on plan to view full size
3. Download for offline use

### Schedule Crew
1. Calendar → Click event
2. Add Crew → Enter name and role
3. They receive email notification

## Tips for Success

✅ **Print Clear Barcodes**: Use at least 1 inch wide, high contrast
✅ **Add Emails**: Enable notifications for better communication
✅ **Use Events**: Link everything (pick lists, stage plans) to events
✅ **Mobile Friendly**: Crew can access on their phones
✅ **Regular Backups**: Copy `production_crew.db` file weekly
✅ **Good Lighting**: Helps camera scanning work better

## Security Tips

🔒 Change default admin password immediately
🔒 Only give admin access to trusted crew leaders
🔒 Use strong passwords for all accounts
🔒 Keep the database file secure
🔒 Change the SECRET_KEY in app.py

## Need Help?

- **Camera not working?** Try manual entry or different browser
- **Can't connect?** Check firewall and network settings
- **Email not sending?** Check `EMAIL_SETUP.md` configuration
- **Database error?** Delete `production_crew.db` and restart

## Ready to Go!

Your Production Crew Management System is now ready. Add your equipment, schedule your events, and enjoy organized production management! 🎭