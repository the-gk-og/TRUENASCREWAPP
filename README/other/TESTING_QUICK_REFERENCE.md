# 🧪 ShowWise Test Suite - Quick Reference Card

## 📦 What's Included

| File | Purpose | Size |
|------|---------|------|
| `test_all_functions.py` | Main test suite | 800+ lines, 50+ tests |
| `run_tests.sh` | Test runner script | 12 modes, easy commands |
| `requirements-test.txt` | Test dependencies | pytest + plugins |
| `TEST_GUIDE.md` | Detailed documentation | Complete reference |
| `TEST_SUMMARY.md` | Overview & quick start | Getting started |

## ⚡ Quick Commands

```bash
# Install & Run
pip install -r requirements-test.txt
./run_tests.sh all

# Specific Features
./run_tests.sh auth       # Authentication
./run_tests.sh equipment  # Equipment Management
./run_tests.sh events     # Event Management
./run_tests.sh chat       # Chat & Messaging

# Reports
./run_tests.sh coverage   # HTML coverage report
./run_tests.sh report     # HTML test report
./run_tests.sh quick      # Silent run

# Debug
./run_tests.sh debug      # Debug mode
./run_tests.sh failed     # Failed tests only
```

## 📊 Test Coverage Matrix

| Component | Tests | Status |
|-----------|-------|--------|
| Authentication | 7 | ✅ |
| 2FA/TOTP | 4 | ✅ |
| Equipment | 10 | ✅ |
| Events | 5 | ✅ |
| Picklist | 5 | ✅ |
| Chat | 3 | ✅ |
| Dashboard | 2 | ✅ |
| Access Control | 2 | ✅ |
| Error Handling | 2 | ✅ |
| Helpers | 2 | ✅ |
| Models | 3 | ✅ |
| Integration | 2 | ✅ |
| **TOTAL** | **50+** | **✅** |

## 🎯 Test Classes at a Glance

```
TestAuthRoutes                    (7 tests)
TestTwoFactorAuth                 (4 tests)
TestEquipmentRoutes              (10 tests)
TestChatRoutes                    (3 tests)
TestDashboardRoutes               (2 tests)
TestEventRoutes                   (5 tests)
TestPicklistRoutes                (5 tests)
TestErrorHandlers                 (2 tests)
TestAuthDecorators                (2 tests)
TestHelperFunctions               (2 tests)
TestDatabaseModels                (3 tests)
TestIntegration                   (2 tests)
```

## 🔑 Key Features Tested

### Authentication ✅
- Valid/Invalid login
- Remember Me
- Logout
- Session management
- 2FA setup/verification

### Permissions ✅
- Login required decorator
- Crew-only decorator
- Admin-only routes
- Role-based access

### Equipment ✅
- Add/Update/Delete
- Barcode search
- List all
- Admin restrictions

### Events ✅
- Create
- Edit
- Delete
- Retrieve

### Chat ✅
- Inbox view
- Rocket.Chat integration
- Message streams

### Picklist ✅
- Add items
- Toggle status
- Delete items

### Database ✅
- User model
- Event model
- Equipment model

## 🚀 Workflow Examples

### Test All Features
```bash
./run_tests.sh all
```

### Test Just Login
```bash
pytest test_all_functions.py::TestAuthRoutes::test_login_valid_credentials -v
```

### See Coverage
```bash
./run_tests.sh coverage
# Then open htmlcov/index.html
```

### Debug Failing Test
```bash
./run_tests.sh debug
# Will drop into debugger on first failure
```

## 📈 Expected Output

```
test_all_functions.py::TestAuthRoutes::test_login_valid_credentials PASSED [ 2%]
test_all_functions.py::TestAuthRoutes::test_logout PASSED [ 4%]
test_all_functions.py::TestEquipmentRoutes::test_equipment_list PASSED [ 6%]
...
==================== 50 passed in 25.34s ====================
```

## 🔍 File Locations

```
ShowWise/
├── test_all_functions.py          ← Main test file
├── run_tests.sh                   ← Test runner script
├── requirements-test.txt          ← Dependencies
├── TEST_GUIDE.md                  ← Full documentation
├── TEST_SUMMARY.md                ← Overview (this folder)
├── app.py                         ← App being tested
└── ...
```

## 🛠️ Pytest Direct Commands

```bash
# Run all with verbose output
pytest test_all_functions.py -v

# Run with coverage
pytest test_all_functions.py --cov=app -v

# Run specific class
pytest test_all_functions.py::TestAuthRoutes -v

# Run with HTML report
pytest test_all_functions.py --html=report.html --self-contained-html

# Show slowest tests
pytest test_all_functions.py --durations=10

# Run in parallel (if xdist installed)
pytest test_all_functions.py -n auto
```

## 🎓 Test Fixtures Available

| Fixture | Details |
|---------|---------|
| `client` | HTTP test client for making requests |
| `test_user` | Regular user (testuser/password123) |
| `admin_user` | Admin account (admin/admin123) |
| `cast_user` | Cast member (castmember/cast123) |
| `test_event` | Sample event for testing |

## 💾 Setup Checklist

- [ ] Install pytest: `pip install -r requirements-test.txt`
- [ ] Verify: `pytest --version`
- [ ] Run tests: `./run_tests.sh all`
- [ ] Check coverage: `./run_tests.sh coverage`
- [ ] Review results: Open `htmlcov/index.html`

## 🎯 Common Patterns

### Test Login Flow
```python
client.post('/login', data={
    'username': 'testuser',
    'password': 'password123'
})
response = client.get('/dashboard')
assert response.status_code == 200
```

### Test API Endpoint
```python
response = client.post('/api/equipment/add',
    json={'barcode': '123', 'name': 'Test'},
    content_type='application/json'
)
assert response.status_code == 200
```

### Test Database
```python
user = User(username='test', email='test@test.com')
db.session.add(user)
db.session.commit()
assert User.query.filter_by(username='test').first()
```

## 📞 Support

**Issue**: Tests won't run  
**Fix**: `pip install -r requirements-test.txt && pytest --version`

**Issue**: Import errors  
**Fix**: Ensure you're in ShowWise directory and app.py exists

**Issue**: Database locked  
**Fix**: `rm production_crew.db` then retry

## 🏆 Best Practices

✅ Run tests before committing  
✅ Keep tests independent  
✅ Use meaningful test names  
✅ Test both success and failure cases  
✅ Mock external services  
✅ Maintain >80% coverage  

## 📚 Documentation

- **Detailed Guide**: See `TEST_GUIDE.md`
- **Overview**: See `TEST_SUMMARY.md`
- **Quick Card**: You're reading it! 📍

---

**Ready to test?** → `./run_tests.sh all`

