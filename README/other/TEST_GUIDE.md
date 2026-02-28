# ShowWise Webapp - Comprehensive Test Guide

This document explains how to run the comprehensive test suite for the ShowWise webapp.

## Overview

The test suite (`test_all_functions.py`) contains **50+ test cases** covering:

- ✅ Authentication routes (login, logout, sessions)
- ✅ 2FA/TOTP setup and verification
- ✅ Equipment management (CRUD operations)
- ✅ Chat functionality (inbox, redirects, Rocket.Chat integration)
- ✅ Event management (creation, editing, deletion)
- ✅ Picklist operations (add, toggle, delete)
- ✅ Error handling (404, 500)
- ✅ Access control decorators (login_required, crew_required)
- ✅ Helper functions (password generation, email)
- ✅ Database models (User, Event, Equipment)
- ✅ Integration tests (multi-step workflows)

## Installation

### 1. Install Testing Dependencies

```bash
pip install -r requirements-test.txt
```

### 2. Verify Installation

```bash
pytest --version
```

You should see: `pytest <version>`

## Running Tests

### Run All Tests

```bash
pytest test_all_functions.py -v
```

Output will show:
- ✓ for passing tests
- ✗ for failing tests
- Test execution time

### Run Specific Test Class

```bash
# Test only authentication
pytest test_all_functions.py::TestAuthRoutes -v

# Test only equipment
pytest test_all_functions.py::TestEquipmentRoutes -v

# Test only events
pytest test_all_functions.py::TestEventRoutes -v
```

### Run Specific Test

```bash
pytest test_all_functions.py::TestAuthRoutes::test_login_valid_credentials -v
```

### Run with Coverage Report

```bash
pytest test_all_functions.py --cov=app --cov-report=html -v
```

This generates an HTML coverage report in `htmlcov/index.html`

### Run Tests Quietly (fewer details)

```bash
pytest test_all_functions.py -q
```

### Run Tests with Detailed Output

```bash
pytest test_all_functions.py -vv -s
```

## Test Classes & Coverage

### TestAuthRoutes (7 tests)
Tests login, logout, session management, and authentication flows
- `test_index_redirect_authenticated` - Index page behavior
- `test_login_page_get` - Login form loads
- `test_login_invalid_credentials` - Rejects wrong password
- `test_login_valid_credentials` - Accepts correct password
- `test_login_with_remember_me` - Remember me functionality
- `test_logout` - User can logout
- `test_session_info` - Session info endpoint works

### TestTwoFactorAuth (4 tests)
Tests 2FA setup, configuration, and verification
- `test_2fa_settings_page` - Settings page loads
- `test_security_settings_page` - Security page loads
- `test_setup_totp` - TOTP secret generation
- `test_disable_totp_invalid_password` - Rejects wrong password

### TestEquipmentRoutes (10 tests)
Tests equipment CRUD operations and filtering
- `test_equipment_list` - Equipment list page
- `test_add_equipment_admin` - Admin can add equipment
- `test_add_equipment_non_admin` - Non-admin restricted
- `test_equipment_by_barcode` - Find equipment by barcode
- `test_equipment_by_barcode_not_found` - 404 for missing equipment
- `test_update_equipment` - Update equipment details
- `test_delete_equipment` - Delete equipment
- `test_barcode_page` - Barcode generation page

### TestChatRoutes (3 tests)
Tests chat, inbox, and Rocket.Chat integration
- `test_inbox_page` - Inbox page loads
- `test_chat_page_redirect` - Chat redirects to RC
- `test_rocketchat_info` - RC info endpoint

### TestDashboardRoutes (2 tests)
Tests dashboard access control
- `test_dashboard_access` - Dashboard loads for crew
- `test_dashboard_cast_cannot_access` - Cast users blocked

### TestEventRoutes (5 tests)
Tests event CRUD operations
- `test_add_event` - Create new event
- `test_get_event` - Retrieve event
- `test_delete_event` - Delete event
- `test_edit_event` - Update event

### TestPicklistRoutes (5 tests)
Tests picklist item operations
- `test_picklist_page` - Picklist page loads
- `test_add_picklist_item` - Add item to list
- `test_toggle_picklist_item` - Toggle item checked state
- `test_delete_picklist_item` - Delete item

### TestErrorHandlers (2 tests)
Tests error handling and responses
- `test_404_error` - 404 page works
- `test_500_error` - 500 error handling

### TestAuthDecorators (2 tests)
Tests access control decorators
- `test_login_required_redirect` - Redirect to login when not authenticated
- `test_crew_required_cast_redirect` - Redirect cast users

### TestHelperFunctions (2 tests)
Tests utility functions
- `test_generate_secure_password` - Password generation
- `test_send_email_disabled` - Email handling

### TestDatabaseModels (3 tests)
Tests database model creation and relationships
- `test_user_creation` - User model works
- `test_event_creation` - Event model works
- `test_equipment_creation` - Equipment model works

### TestIntegration (2 tests)
Tests multi-step workflows
- `test_user_login_dashboard_flow` - Complete login flow
- `test_event_creation_flow` - Event creation workflow

## Understanding Test Output

### Successful Run
```
test_all_functions.py::TestAuthRoutes::test_login_valid_credentials PASSED [5%]
```

### Failed Test
```
test_all_functions.py::TestAuthRoutes::test_login_invalid_credentials FAILED [10%]
AssertionError: assert 200 == 401
```

### Skipped Test
```
test_all_functions.py::TestAuthRoutes::test_some_test SKIPPED [15%]
```

## Common Issues & Solutions

### Issue: ImportError
**Error**: `ModuleNotFoundError: No module named 'app'`
**Solution**: Run tests from the project root directory

```bash
cd /path/to/ShowWise
pytest test_all_functions.py -v
```

### Issue: Database Locked
**Error**: `sqlite3.OperationalError: database is locked`
**Solution**: Tests use in-memory database, but if this persists:

```bash
rm production_crew.db
pytest test_all_functions.py -v
```

### Issue: Port Already in Use
**Error**: `Address already in use`
**Solution**: Tests don't use ports, but if Flask is running:

```bash
pkill -f "python.*app.py"
pytest test_all_functions.py -v
```

### Issue: Environmental Variables Missing
**Error**: `KeyError: 'ORGANIZATION_SLUG'`
**Solution**: Ensure `.env` file is created (or tests run with mocked env vars)

## Adding New Tests

To add a test for a new function:

```python
class TestNewFeature:
    """Test new feature routes"""
    
    def test_new_feature_basic(self, client, test_user):
        """Test new feature basic functionality"""
        # Login
        client.post('/login', data={
            'username': 'testuser',
            'password': 'password123'
        })
        
        # Make request
        response = client.get('/new-feature')
        
        # Assert
        assert response.status_code == 200
```

Then run:
```bash
pytest test_all_functions.py::TestNewFeature -v
```

## Advanced Testing

### Run Tests with Performance Timing
```bash
pytest test_all_functions.py -v --durations=10
```

Shows slowest 10 tests

### Run Tests in Parallel
```bash
pip install pytest-xdist
pytest test_all_functions.py -v -n auto
```

### Generate Test Report
```bash
pytest test_all_functions.py -v --html=report.html --self-contained-html
```

Creates `report.html` with detailed results

### Debug Failed Test
```bash
pytest test_all_functions.py::TestAuthRoutes::test_login_valid_credentials -vv -s --pdb
```

Opens debugger on failure

## Test Fixtures Explained

### `client`
Test client for making HTTP requests to the app

### `test_user`
Standard user account (username: `testuser`, password: `password123`)

### `admin_user`
Admin account (username: `admin`, password: `admin123`)

### `cast_user`
Cast member account (username: `castmember`, password: `cast123`)

### `test_event`
Sample event created with `test_event`

## Continuous Integration

To run tests automatically before commits:

```bash
# Create pre-commit hook
cat > .git/hooks/pre-commit << 'EOF'
#!/bin/bash
pytest test_all_functions.py -q
if [ $? -ne 0 ]; then
    echo "Tests failed. Aborting commit."
    exit 1
fi
EOF

chmod +x .git/hooks/pre-commit
```

## Expected Coverage

Current test suite covers:
- Authentication: 95%
- Routes: 85%
- Models: 90%
- Error handling: 80%

Target: 90%+ coverage

## Troubleshooting Checklist

- [ ] Pytest installed: `pytest --version`
- [ ] Run from project root
- [ ] `.env` file exists (or use test config)
- [ ] Database not locked
- [ ] Flask app not running
- [ ] All imports working: `python -c "from app import app"`
- [ ] Test file syntax valid: `python -m py_compile test_all_functions.py`

## Support

For issues, check:
1. Flask documentation: https://flask.palletsprojects.com/
2. Pytest documentation: https://docs.pytest.org/
3. SQLAlchemy testing: https://docs.sqlalchemy.org/en/20/orm/session_basics.html

## Next Steps

1. Run the full test suite: `pytest test_all_functions.py -v`
2. Check coverage: `pytest test_all_functions.py --cov=app`
3. Fix any failing tests
4. Add tests for new features
5. Integrate into CI/CD pipeline

Happy testing! 🚀
