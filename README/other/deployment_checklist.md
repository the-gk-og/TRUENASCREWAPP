# Pre-Launch Deployment Checklist

Complete this checklist before going live with your Production Crew Management System.

## 🔐 Security Preparation

- [ ] Change SECRET_KEY in prod_crew_app.py
  - [ ] Generate random string: https://randomkeygen.com/
  - [ ] Replace in app.config['SECRET_KEY']
  - [ ] Do NOT commit the real key (use env variable on Render)

- [ ] Change default admin password
  - [ ] Login with admin/admin123
  - [ ] Go to Admin panel
  - [ ] Delete default admin user
  - [ ] Create new admin account with strong password

- [ ] Set up email (optional but recommended)
  - [ ] Create Gmail account or use existing
  - [ ] Enable 2FA on Gmail
  - [ ] Generate App Password
  - [ ] Save in EMAIL_SETUP.md for reference

- [ ] Review user permissions
  - [ ] Add all crew members
  - [ ] Set admin users carefully
  - [ ] Regular users have limited access

- [ ] Set strong database backup location
  - [ ] Backups will be in /backups folder
  - [ ] Ensure /backups folder is included in .gitignore
  - [ ] Plan regular backup downloads

## 📋 Code Preparation

- [ ] All files in correct locations
  - [ ] prod_crew_app.py in root directory
  - [ ] All HTML files in /templates folder
  - [ ] requirements.txt in root directory
  - [ ] Procfile in root directory

- [ ] Dependencies verified
  ```
  pip install -r requirements.txt
  ```
  - [ ] All packages install successfully
  - [ ] No version conflicts
  - [ ] gunicorn 21.2.0 installed

- [ ] Environment variables documented
  - [ ] Create .env file for local testing
  - [ ] Document all required variables
  - [ ] Note which are optional

- [ ] Test locally first
  - [ ] Run: python prod_crew_app.py
  - [ ] Access: http://localhost:5000
  - [ ] Test login (admin/admin123)
  - [ ] Test each feature

## 📱 Feature Testing

- [ ] Equipment Management
  - [ ] Add equipment works
  - [ ] Edit equipment works
  - [ ] Delete equipment works
  - [ ] Search equipment works
  - [ ] Barcode scanning works locally

- [ ] Barcode Scanning
  - [ ] Camera access prompts
  - [ ] Scanner activates
  - [ ] Detects barcodes
  - [ ] Falls back to manual entry

- [ ] Pick Lists
  - [ ] Create pick list works
  - [ ] Add items works
  - [ ] Check off items works
  - [ ] Delete items works

- [ ] Calendar
  - [ ] Add events works
  - [ ] Edit events works
  - [ ] Delete events works
  - [ ] Subscribe button works

- [ ] Admin Features
  - [ ] Create backups works
  - [ ] Download backups works
  - [ ] Restore from backup works
  - [ ] CSV import works
  - [ ] SheetDB import works

- [ ] Email (if configured)
  - [ ] Add user with email
  - [ ] Assign to event
  - [ ] Check email received
  - [ ] Email contains correct info

## 🌐 Render Deployment

- [ ] GitHub account created
  - [ ] Account ready to use
  - [ ] Can push code

- [ ] Code pushed to GitHub
  - [ ] Repository created
  - [ ] All code committed
  - [ ] Procfile included
  - [ ] requirements.txt included
  - [ ] .gitignore configured

- [ ] .gitignore configured
  ```
  production_crew.db
  uploads/*
  backups/*
  .env
  __pycache__/
  *.pyc
  ```

- [ ] Render account created
  - [ ] Account active
  - [ ] Can create web services

- [ ] GitHub connected to Render
  - [ ] Repository authorized
  - [ ] Render can see repos

- [ ] Render service created
  - [ ] Web service configured
  - [ ] GitHub repo connected
  - [ ] Branch set to main

- [ ] Environment variables set on Render
  - [ ] SECRET_KEY set (random string)
  - [ ] MAIL_SERVER: smtp.gmail.com
  - [ ] MAIL_PORT: 587
  - [ ] MAIL_USERNAME: your-email@gmail.com
  - [ ] MAIL_PASSWORD: app-password
  - [ ] MAIL_DEFAULT_SENDER: your-email@gmail.com

- [ ] Service deployed
  - [ ] Deployment started
  - [ ] Build logs show success
  - [ ] Service shows "Live"
  - [ ] URL assigned

## 🧪 Production Testing

- [ ] Test on Render
  - [ ] Visit your URL
  - [ ] Page loads correctly
  - [ ] Design looks good
  - [ ] Navigation works

- [ ] Test login on Render
  - [ ] Login page loads
  - [ ] Can log in with new admin account
  - [ ] Dashboard displays correctly

- [ ] Test camera on Render
  - [ ] Visit Equipment page
  - [ ] Scan barcode button works
  - [ ] Camera permission prompt appears
  - [ ] Camera activates
  - [ ] Barcode scanning works

- [ ] Test on mobile device
  - [ ] Access via mobile browser
  - [ ] Site is responsive
  - [ ] All buttons are clickable
  - [ ] Camera works on mobile
  - [ ] Forms are usable

- [ ] Test database
  - [ ] Add test equipment
  - [ ] Create test event
  - [ ] Add test crew member
  - [ ] Data persists on reload

- [ ] Test backup
  - [ ] Create backup on Render
  - [ ] Download backup file
  - [ ] Verify file is not empty
  - [ ] Store in safe location

## 📊 Data Preparation

- [ ] Equipment list ready
  - [ ] All equipment documented
  - [ ] Barcodes assigned
  - [ ] Locations finalized
  - [ ] Categories defined

- [ ] Equipment entered in system
  - [ ] Via CSV import or SheetDB (recommended)
  - [ ] Or manually added
  - [ ] All entries verified
  - [ ] Locations are accurate

- [ ] Barcodes created
  - [ ] Barcodes generated (free online tools)
  - [ ] Printed on stickers or labels
  - [ ] Attached to equipment boxes
  - [ ] QR codes tested with camera

- [ ] Crew members added
  - [ ] All crew members in system
  - [ ] Email addresses added
  - [ ] Admin users assigned

- [ ] Events scheduled (optional)
  - [ ] Upcoming events added
  - [ ] Dates and times set
  - [ ] Locations set
  - [ ] Crew assigned

## 📚 Documentation

- [ ] All guides saved/printed
  - [ ] QUICK_START.md
  - [ ] README.md
  - [ ] RENDER_DEPLOYMENT.md
  - [ ] SHEETDB_SETUP.md
  - [ ] EMAIL_SETUP.md
  - [ ] FEATURES_SUMMARY.md

- [ ] Admin docs prepared
  - [ ] How to create backups
  - [ ] How to restore backups
  - [ ] How to add users
  - [ ] How to import equipment

- [ ] User docs prepared
  - [ ] How to scan barcodes
  - [ ] How to use pick lists
  - [ ] How to view calendar
  - [ ] How to check schedule

- [ ] Troubleshooting guide reviewed
  - [ ] Common issues noted
  - [ ] Solutions documented
  - [ ] Support contact info ready

## 👥 Team Training

- [ ] Demo scheduled
  - [ ] Time and date set
  - [ ] All crew invited
  - [ ] Materials prepared

- [ ] Training content prepared
  - [ ] Demo account ready
  - [ ] Sample equipment added
  - [ ] Sample events created
  - [ ] Presentation notes written

- [ ] Training checklist
  - [ ] Show login process
  - [ ] Show dashboard
  - [ ] Demo barcode scanning
  - [ ] Show pick lists
  - [ ] Show calendar
  - [ ] Show email notifications
  - [ ] Show calendar subscription
  - [ ] Answer questions

- [ ] Post-training support
  - [ ] Contact method established
  - [ ] FAQ document ready
  - [ ] Help email/Slack set up
  - [ ] First person to contact identified

## 🎯 Launch Day

- [ ] Final security checks
  - [ ] Confirm SECRET_KEY changed
  - [ ] Confirm new admin password set
  - [ ] Confirm old admin deleted
  - [ ] Confirm email configured (if needed)

- [ ] Final backup
  - [ ] Create and download backup
  - [ ] Store safely
  - [ ] Document backup location

- [ ] Announce to team
  - [ ] Email announcement sent
  - [ ] Link provided: your-app.onrender.com
  - [ ] Initial password provided
  - [ ] Support instructions included

- [ ] Monitor first day
  - [ ] Check Render logs for errors
  - [ ] Respond to questions quickly
  - [ ] Fix any issues immediately
  - [ ] Make notes of problems

- [ ] Celebrate! 🎉
  - [ ] Your system is live!
  - [ ] Crew can start using it
  - [ ] Track production efficiently

## 📅 Post-Launch

### Week 1
- [ ] Monitor daily
- [ ] Fix any bugs
- [ ] Respond to user feedback
- [ ] Create backup daily

### Week 2-4
- [ ] Most issues resolved
- [ ] Crew comfortable with system
- [ ] Plan any feature additions
- [ ] Weekly backups

### Month 2+
- [ ] Regular backups (weekly)
- [ ] Monitor usage patterns
- [ ] Plan optimizations
- [ ] Gather feedback for improvements

## 🔧 Troubleshooting Reference

### Quick fixes during launch:

**Camera not working?**
- Confirm on HTTPS (automatic on Render)
- Check browser permissions
- Try manual barcode entry

**Can't login?**
- Double-check username/password
- Ensure admin account was created
- Try incognito/private mode

**Email not sending?**
- Check App Password is correct
- Verify 2FA is enabled
- Check environment variables on Render

**Database errors?**
- Check logs on Render
- Verify database migrations ran
- Restore from backup if needed

**Slow performance?**
- Normal for Render free tier
- Consider upgrade if persistent
- Check Render metrics dashboard

## ✅ Final Checklist

- [ ] All security steps completed
- [ ] All testing passed
- [ ] All data entered
- [ ] All team trained
- [ ] All documentation ready
- [ ] Launch day confirmed
- [ ] Support plan in place
- [ ] Backups secured
- [ ] Emergency contact info shared

## 🚀 You're Ready!

When all checkboxes are checked, you're ready to go live!

**Deployment time: 15-30 minutes**

Good luck with your production crew management system! 🎭