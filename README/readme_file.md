### 5. Change Default Admin Password

**IMPORTANT:** After first login, create a new admin account and delete the default one for security.

### 6. (Optional) Configure Email Notifications

See `EMAIL_SETUP.md` for detailed instructions on setting up email notifications for crew assignments. Email is completely optional - the app works fine without it!

Quick setup:
```bash
# Create .env file with your email settings
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-app-password
```

## New Features Guide

### 📷 Camera Barcode Scanning

1. Go to Equipment page
2. Click "📱 Scan Barcode"
3. Click "📷 Start Camera"
4. Point your camera at a barcode
5. The system will automatically detect and look up the equipment

**Supported barcode formats:**
- Code 128
- EAN-13, EAN-8
- UPC-A, UPC-E
- Code 39
- Codabar
- Interleaved 2 of 5

### 📧 Email Notifications

When you assign a crew member to an event, they automatically receive an email with:
- Event details (name, date, location)
- Their assigned role
- Link to login (in the message)

**Requirements:**
- User must have an email address set up
- Email server must be configured (see EMAIL_SETUP.md)

### 🗑️ Delete Functionality

**Admins can delete:**
- Equipment items
- Events (also deletes associated pick lists, stage plans, and crew assignments)
- Users (except yourself)
- Stage plans
- Pick list items (anyone can delete these)

**All users can delete:**
- Pick list items they added
- Their own crew assignments (remove themselves from events)

All delete actions include confirmation dialogs to prevent accidents.# Production Crew Management System

A comprehensive web application for managing school production crew equipment, schedules, and events.

## Features

- 📦 **Equipment Tracking** - Barcode scanning system with camera support to track equipment locations
- 📋 **Collaborative Pick Lists** - Team-based checklists for events
- 🎨 **Stage Plan Sharing** - Upload and share stage layouts
- 📅 **Event Calendar** - Schedule events and assign crew members
- 👥 **Crew Scheduling** - Assign roles and track crew availability
- 📧 **Email Notifications** - Automatic email alerts when crew members are assigned to events
- 📷 **Camera Barcode Scanning** - Use your phone or webcam to scan barcodes directly
- 🔐 **Access Control** - User authentication with admin privileges
- 🗑️ **Full Management** - Delete equipment, events, users, and more

## Setup Instructions

### 1. Install Python Requirements

```bash
pip install -r requirements.txt
```

### 2. Create Folder Structure

Create the following folders in your project directory:

```bash
mkdir templates uploads
```

### 3. Save Template Files

Save all the HTML templates in the `templates` folder:
- `base.html`
- `login.html`
- `dashboard.html`
- `equipment.html`
- `picklist.html`
- `stageplans.html`
- `calendar.html`
- `event_detail.html`
- `admin.html`

### 4. Run the Application

```bash
python app.py
```

The application will:
- Create the SQLite database automatically
- Create a default admin account:
  - Username: `admin`
  - Password: `admin123`
- Start the server on `http://0.0.0.0:5000`

### 5. Change Default Admin Password

**IMPORTANT:** After first login, create a new admin account and delete the default one for security.

## Accessing on School Network

### Option 1: Direct IP Access
1. Find your laptop's local IP address:
   - Windows: `ipconfig` (look for IPv4 Address)
   - Mac/Linux: `ifconfig` or `ip addr`
2. Access from any device on the school network: `http://YOUR_IP:5000`

### Option 2: Set a Hostname
Configure your laptop with a static hostname that can be accessed via `http://hostname.local:5000`

## Google Sheets Integration for Equipment

To sync equipment from Google Sheets:

1. Export your Google Sheet as CSV
2. Use the Admin panel to bulk import equipment (you'll need to add this feature or manually add items)
3. Each item should have:
   - Barcode (unique identifier)
   - Name
   - Category
   - Storage Location
   - Notes

## Using Barcodes

### Camera Scanning (New!):
1. Navigate to Equipment page
2. Click "📱 Scan Barcode" 
3. Click "📷 Start Camera"
4. Point camera at barcode
5. System automatically detects and displays equipment info

### Manual Entry:
1. Go to Equipment page and click "📱 Scan Barcode"
2. Type the barcode number in the text field
3. Click "Look Up" or press Enter
4. The system will display the item's location instantly

### For Scanning:
1. Generate barcodes for your equipment (you can use free online barcode generators)
2. Print and attach them to equipment boxes
3. Users can scan with camera or enter the barcode manually
4. The system will display the item's location instantly

### Barcode Format Recommendations:
- Use Code 128 or QR codes for best camera scanning results
- Include the barcode number on the label for manual entry
- Format: `PROD-XXXX` (e.g., PROD-0001, PROD-0002)
- Make sure barcodes are printed clearly and at adequate size (at least 1 inch wide)

## Mobile Access

The application is mobile-responsive. Crew members can:
- Scan barcodes using their phone's camera (works on iOS and Android)
- Enter barcodes manually as fallback
- Check off pick list items
- View stage plans
- Check their schedule
- Receive email notifications about assignments

**Camera Permissions:**
- On first use, your browser will ask for camera permission
- Grant permission to enable barcode scanning
- If denied, you can still enter barcodes manually

## Security Recommendations

1. **Change the SECRET_KEY** in `app.py`:
   ```python
   app.config['SECRET_KEY'] = 'your-unique-secret-key-here'
   ```

2. **Use HTTPS** if exposing publicly (consider using ngrok or reverse proxy)

3. **Regular Backups**: Backup the `production_crew.db` file regularly

4. **Limit Admin Access**: Only give admin privileges to trusted crew leaders

## Database Location

The SQLite database (`production_crew.db`) is created in the same directory as `app.py`.

## File Uploads

Stage plans and images are stored in the `uploads/` folder. Maximum file size: 16MB.

## Troubleshooting

### Can't Access from Other Devices
- Check firewall settings on the host laptop
- Ensure all devices are on the same network
- Try accessing via IP address instead of hostname

### Database Errors
- Delete `production_crew.db` and restart to recreate
- Check file permissions on the database file

### Upload Errors
- Verify the `uploads` folder exists and is writable
- Check file size (max 16MB)

### Camera Not Working
- Check browser permissions (should see camera permission prompt)
- Try a different browser (Chrome/Firefox recommended)
- Ensure you're using HTTPS or localhost (cameras require secure context)
- Fall back to manual barcode entry if camera issues persist

### Email Not Sending
- Check `EMAIL_SETUP.md` for configuration details
- Verify environment variables are set correctly
- Look for error messages in the Flask console
- Email is optional - app works fine without it

### Delete Not Working
- Ensure you're logged in as an admin for protected deletions
- Check the browser console for error messages
- Some items (like events) will also delete related items

## Future Enhancements

Consider adding:
- ~~Camera-based barcode scanning~~ ✅ **ADDED!**
- ~~Email notifications for event assignments~~ ✅ **ADDED!**
- SMS notifications as alternative to email
- Equipment checkout/check-in system
- Conflict checking for equipment double-booking
- Export reports to PDF
- Mobile app version
- Integration with Google Calendar
- Maintenance logs for equipment

## Support

For issues or questions, contact your school's tech crew supervisor.

## License

This is custom software for educational use.