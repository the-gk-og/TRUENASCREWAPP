#!/usr/bin/env python3
"""
ShowWise System Verification Script
Run this to check if everything is configured correctly
"""

from app import app, db, Equipment, HiredEquipment, User
from sqlalchemy import inspect, text
from datetime import datetime, timedelta
import sys

def print_header(text):
    print("\n" + "="*60)
    print(f"  {text}")
    print("="*60)

def print_result(passed, message):
    icon = "✅" if passed else "❌"
    status = "PASS" if passed else "FAIL"
    print(f"{icon} {status}: {message}")
    return passed

def check_database_schema():
    """Check if all required columns exist"""
    print_header("DATABASE SCHEMA CHECK")
    
    all_passed = True
    
    with app.app_context():
        inspector = inspect(db.engine)
        
        # Check equipment table
        equipment_cols = {col['name']: col for col in inspector.get_columns('equipment')}
        
        required_equipment_cols = ['id', 'barcode', 'name', 'quantity_owned']
        print("\nEquipment table columns:")
        for col_name in required_equipment_cols:
            exists = col_name in equipment_cols
            all_passed = print_result(exists, f"Column '{col_name}'") and all_passed
        
        # Check hired_equipment table
        tables = inspector.get_table_names()
        has_hired = 'hired_equipment' in tables
        all_passed = print_result(has_hired, "Table 'hired_equipment' exists") and all_passed
        
        if has_hired:
            hired_cols = {col['name']: col for col in inspector.get_columns('hired_equipment')}
            required_hired_cols = ['id', 'name', 'hire_date', 'return_date', 'is_returned']
            print("\nHired equipment table columns:")
            for col_name in required_hired_cols:
                exists = col_name in hired_cols
                all_passed = print_result(exists, f"Column '{col_name}'") and all_passed
    
    return all_passed

def check_admin_user():
    """Check if admin user exists and has admin privileges"""
    print_header("ADMIN USER CHECK")
    
    all_passed = True
    
    with app.app_context():
        admin = User.query.filter_by(username='admin').first()
        
        if admin:
            all_passed = print_result(True, "Admin user exists")
            all_passed = print_result(admin.is_admin, f"User has admin privileges") and all_passed
            
            if not admin.is_admin:
                print("\n   🔧 Fixing admin privileges...")
                admin.is_admin = True
                db.session.commit()
                print("   ✅ Fixed! Please log out and back in.")
        else:
            all_passed = print_result(False, "Admin user not found")
            print("\n   ⚠️  No admin user found. Create one with:")
            print("      python -c \"from app import app, db, User; from werkzeug.security import generate_password_hash; \\")
            print("                 with app.app_context(): u = User(username='admin', password_hash=generate_password_hash('password'), is_admin=True); \\")
            print("                 db.session.add(u); db.session.commit()\"")
    
    return all_passed

def test_equipment_quantity_save():
    """Test if equipment quantity can be saved"""
    print_header("EQUIPMENT QUANTITY TEST")
    
    with app.app_context():
        # Clean up old test
        old_test = Equipment.query.filter_by(barcode='VERIFY_TEST').first()
        if old_test:
            db.session.delete(old_test)
            db.session.commit()
        
        # Create test equipment with quantity
        test_eq = Equipment(
            barcode='VERIFY_TEST',
            name='Verification Test Item',
            quantity_owned=42
        )
        
        try:
            db.session.add(test_eq)
            db.session.commit()
            
            # Retrieve and check
            retrieved = Equipment.query.filter_by(barcode='VERIFY_TEST').first()
            
            if retrieved and retrieved.quantity_owned == 42:
                print_result(True, f"Quantity saved correctly (value: {retrieved.quantity_owned})")
                passed = True
            else:
                actual = retrieved.quantity_owned if retrieved else None
                print_result(False, f"Quantity not saved (expected: 42, got: {actual})")
                passed = False
            
            # Cleanup
            if retrieved:
                db.session.delete(retrieved)
                db.session.commit()
            
            return passed
            
        except Exception as e:
            print_result(False, f"Error saving equipment: {str(e)}")
            db.session.rollback()
            return False

def test_bulk_delete():
    """Test if bulk delete works"""
    print_header("BULK DELETE TEST")
    
    with app.app_context():
        try:
            # Create test items
            test_items = []
            for i in range(3):
                item = HiredEquipment(
                    name=f'Verify Test {i+1}',
                    hire_date=datetime.now(),
                    return_date=datetime.now() + timedelta(days=7)
                )
                db.session.add(item)
                test_items.append(item)
            
            db.session.commit()
            test_ids = [item.id for item in test_items]
            print(f"   Created test items with IDs: {test_ids}")
            
            # Attempt bulk delete
            deleted_count = 0
            for item_id in test_ids:
                item = HiredEquipment.query.get(item_id)
                if item:
                    db.session.delete(item)
                    deleted_count += 1
            
            db.session.commit()
            print(f"   Attempted to delete {deleted_count} items")
            
            # Verify deletion
            remaining = [HiredEquipment.query.get(id) for id in test_ids]
            remaining = [r for r in remaining if r is not None]
            
            if len(remaining) == 0:
                print_result(True, f"All {deleted_count} items deleted successfully")
                return True
            else:
                print_result(False, f"{len(remaining)} items still exist after deletion")
                # Cleanup remaining
                for item in remaining:
                    db.session.delete(item)
                db.session.commit()
                return False
                
        except Exception as e:
            print_result(False, f"Error during bulk delete: {str(e)}")
            db.session.rollback()
            return False

def check_routes():
    """Check if required routes exist"""
    print_header("ROUTES CHECK")
    
    all_passed = True
    
    with app.app_context():
        # Get all routes
        routes = {}
        for rule in app.url_map.iter_rules():
            routes[rule.endpoint] = {
                'path': str(rule),
                'methods': list(rule.methods - {'HEAD', 'OPTIONS'})
            }
        
        # Check required routes
        required_routes = [
            ('equipment_list', 'GET'),
            ('add_equipment', 'POST'),
            ('update_equipment', 'PUT'),
            ('hired_equipment_list', 'GET'),
            ('bulk_delete_hired', 'POST'),
            ('picklist', 'GET'),
            ('check_equipment_quantity', 'POST')
        ]
        
        for endpoint, method in required_routes:
            exists = endpoint in routes
            if exists:
                has_method = method in routes[endpoint]['methods']
                status = f"Route '{endpoint}' with {method}"
                all_passed = print_result(has_method, status) and all_passed
            else:
                all_passed = print_result(False, f"Route '{endpoint}' missing") and all_passed
    
    return all_passed

def main():
    """Run all checks"""
    print("\n" + "╔" + "="*58 + "╗")
    print("║" + " "*15 + "SHOWWISE SYSTEM VERIFICATION" + " "*15 + "║")
    print("╚" + "="*58 + "╝")
    
    results = {
        'Database Schema': check_database_schema(),
        'Admin User': check_admin_user(),
        'Equipment Quantity': test_equipment_quantity_save(),
        'Bulk Delete': test_bulk_delete(),
        'Routes': check_routes()
    }
    
    # Summary
    print_header("SUMMARY")
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    print(f"\nTests passed: {passed}/{total}")
    print("\nDetails:")
    for test_name, result in results.items():
        icon = "✅" if result else "❌"
        print(f"  {icon} {test_name}")
    
    if passed == total:
        print("\n🎉 ALL CHECKS PASSED! Your system is ready.")
        return 0
    else:
        print(f"\n⚠️  {total - passed} check(s) failed. See details above.")
        print("\nCommon fixes:")
        print("  1. Run: python migrate_hired_equipment.py")
        print("  2. Restart Flask server")
        print("  3. Hard refresh browser (Ctrl+F5)")
        print("  4. Check app.py has all updated routes")
        return 1

if __name__ == '__main__':
    sys.exit(main())