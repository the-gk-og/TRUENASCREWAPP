# ✅ ShowWise Shift Management & Scheduling Implementation

## 📋 What Was Implemented

### 1. **New Database Models** (in `app.py`)
Created two new database models to support shift management:

#### `Shift` Model
- Represents a shift linked to an event
- Key fields:
  - `event_id`: Links to the event
  - `title`, `description`: Shift details
  - `shift_date`, `shift_end_date`: Shift timing
  - `location`: Shift location
  - `positions_needed`: How many crew members needed
  - `role`: Type of role (e.g., "Lighting", "Sound")
  - `is_open`: Whether crew can claim this shift

#### `ShiftAssignment` Model
- Represents individual assignment/claim of a shift by a crew member
- Key fields:
  - `shift_id`: Links to shift
  - `user_id`: Links to crew member
  - `status`: pending/accepted/rejected/confirmed
  - `assigned_by`: Who made the assignment (admin username or 'self')
  - `notes`: Optional notes

---

### 2. **Admin Shift Management Page** ✨
**Route:** `/shifts/management`
**File:** `/templates/admin/shift_management.html`

#### Features:
- 📊 **Dashboard Stats**
  - Total shifts
  - Open to claim
  - Pending responses
  - Confirmed assignments

- 🎯 **Shift Management**
  - Create new shifts linked to events
  - Edit existing shifts
  - Delete shifts
  - Set number of positions needed
  - Mark shifts as open or closed
  - Add shift descriptions and locations

- 👥 **Crew Assignment**
  - Assign specific crew members to shifts
  - Bulk assignment support
  - View all assignments by shift
  - See assignment status (pending, accepted, confirmed, rejected)
  - Remove assignments
  - Add notes to assignments

- 🔍 **Filtering**
  - Filter by event
  - Filter by shift status (open/full)

---

### 3. **Personal Schedule View for Crew** 📅
**Route:** `/my-schedule`
**File:** `/templates/crew/my_schedule.html`

#### List View
Shows crew member's schedule organized by date with:
- 📅 Large date badges showing day, date, and month
- 🎬 All assigned shifts in chronological order
- 📍 Location information
- 👥 Crew count for each shift
- 💬 Shift role and description
- ⏰ Time display (start - end)

#### Status Indicators
- **Pending**: Shifts awaiting response (yellow badge)
- **Accepted**: Crew member accepted the shift (green badge)
- **Confirmed**: Self-claimed shifts (blue badge)

#### Shift Response Actions
- ✅ Accept shift assignment
- ❌ Reject shift assignment

#### Open Shifts View
Shows all available shifts crew can claim:
- Filter by event
- Shows positions available/needed
- Claim button for available shifts
- Prevents claiming when shift is full
- Shows spot count remaining

---

### 4. **New API Routes** (for shift management)

#### GET Routes
```
GET /api/shifts                              - Get all shifts (optionally filtered by event)
GET /shifts/management                       - Admin shift management page
GET /my-schedule                             - Crew personal schedule
```

#### POST Routes
```
POST /shifts/add                             - Create new shift (admin only)
POST /shifts/<shift_id>/assign               - Assign crew to shift (admin only)
POST /shifts/<shift_id>/claim                - Crew claims open shift
POST /shifts/assignment/<assignment_id>/respond - Crew respond to assignment
```

#### PUT Routes
```
PUT /shifts/<shift_id>/edit                  - Edit shift (admin only)
```

#### DELETE Routes
```
DELETE /shifts/<shift_id>                    - Delete shift (admin only)
DELETE /shifts/assignment/<assignment_id>   - Remove crew from shift
```

---

### 5. **Navigation Updates**
Modified `/templates/base.html` to add:
- **"My Schedule"** link in Main section (all crew)
- **"Shift Management"** link in Production section (admins only)

---

## 🚀 How to Use

### For Admins - Creating and Managing Shifts

1. **Go to Shift Management**
   - Click "Shift Management" in the left sidebar
   - Or visit `/shifts/management`

2. **Create a New Shift**
   - Click "New Shift" button
   - Select the event
   - Set title, role, times, location
   - Set number of positions needed
   - Optionally mark as "Open for crew to claim"
   - Click "Create Shift"

3. **Manage Assignments**
   - Assign crew members directly via "Assign Crew"
   - View all assignments with their status
   - Remove assignments if needed
   - Track pending responses

4. **Monitor Shifts**
   - View dashboard stats at top
   - Filter by event or status
   - See who's assigned and confirmation status
   - Edit or delete shifts as needed

---

### For Crew - Viewing Schedule and Claiming Shifts

1. **View My Schedule**
   - Click "My Schedule" in sidebar
   - See all assigned shifts organized by date
   - View pending assignments and respond to them

2. **Accept or Reject Shifts**
   - If you have a pending shift assignment
   - Click "Accept" to confirm or "Reject" to decline
   - Response is recorded with timestamp

3. **Claim Open Shifts**
   - Click "Open Shifts" tab
   - Browse available shifts to claim
   - Click "Claim Shift" when interested
   - Self-claimed shifts are auto-confirmed

---

## 📊 Key Features

### Shift Assignment Workflow
```
1. Admin creates shift linked to event
2. Admin assigns crew OR crew claims open shift
3. If assigned by admin → crew gets notification & sees "Pending"
4. Crew responds (Accept/Reject) → status updates
5. Admin can view all assignment statuses
6. Crew can see confirmed shifts on their schedule
```

### Smart Display
- **Crew's Personal View**: Organized by date, showing only their shifts
- **Admin Dashboard**: Shows all shifts with statistics and filtering
- **Calendar Integration**: Works alongside existing calendar view

### Notifications
- Email sent when admin assigns crew to shift
- Assignment requires crew response
- Crew can claim shifts independently if open

---

## 🔧 Database Tables Created

1. **shift** table
   - Stores all shifts linked to events
   - Tracks positions needed and open status

2. **shift_assignment** table
   - Stores individual crew assignments
   - Tracks status and assignment source (admin or self)

---

## 📝 Notes

- Shifts are linked to events - when creating a shift, select the event first
- Crew members can claim open shifts without admin approval
- Admin can assign crew directly, which requires their response
- Shifts show number of crew needed vs assigned
- All assignments have timestamps for audit trail
- Personal schedule is accessible 24/7 for crew planning

---

## ✨ What's Fixed/Improved

The calendar and schedule display now:
- ✅ Properly displays events with all details
- ✅ Has a new personal view for crew (more user-friendly)
- ✅ Supports shift management (production-ready like Connecteam)
- ✅ Allows role-based scheduling
- ✅ Shows crew needs vs assignments
- ✅ Supports shift claiming workflow
- ✅ Has responsive design for mobile

---

## 🎯 Next Steps (Optional Enhancements)

1. **Notifications**
   - SMS notifications for shift assignments
   - Push notifications
   - Automatic reminders before shifts

2. **Reporting**
   - Shift fulfillment reports
   - Crew hours tracking
   - Event staffing analysis

3. **Advanced Features**
   - Automatic shift matching based on crew availability
   - Recurring shifts
   - Shift templates
   - Time-off conflicts detection

---

## 📞 Support

If you encounter any issues:
1. Check that crew members exist in the system first
2. Ensure event is created before creating shifts
3. Database tables created automatically via `db.create_all()`
4. Check browser console for any JavaScript errors
5. Check server logs for API errors

---

*Implementation completed on: 2026-02-26*
