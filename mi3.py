# Save as migrate_hired_equipment.py and run: python migrate_hired_equipment.py

from app import app, db, HiredEquipment, HiredEquipmentCheckItem, Equipment
from sqlalchemy import inspect, text

def migrate_database():
    """Add new tables and columns for hired equipment and quantity tracking"""
    
    with app.app_context():
        inspector = inspect(db.engine)
        existing_tables = inspector.get_table_names()
        
        print("🔄 Migrating database for hired equipment features...")
        
        # Check if HiredEquipment table exists
        if 'hired_equipment' not in existing_tables:
            print("📦 Creating HiredEquipment table...")
            db.create_all()
            print("✅ HiredEquipment table created!")
        else:
            print("✓ HiredEquipment table already exists")
        
        # Check if HiredEquipmentCheckItem table exists
        if 'hired_equipment_check_item' not in existing_tables:
            print("✅ Creating HiredEquipmentCheckItem table...")
            db.create_all()
            print("✅ HiredEquipmentCheckItem table created!")
        else:
            print("✓ HiredEquipmentCheckItem table already exists")
        
        # Add quantity_owned column to Equipment table if it doesn't exist
        equipment_columns = [col['name'] for col in inspector.get_columns('equipment')]
        
        if 'quantity_owned' not in equipment_columns:
            print("📦 Adding quantity_owned column to Equipment table...")
            try:
                with db.engine.connect() as conn:
                    conn.execute(text('ALTER TABLE equipment ADD COLUMN quantity_owned INTEGER DEFAULT 1'))
                    conn.commit()
                print("✅ quantity_owned column added!")
                
                # Set default quantity for existing equipment
                print("🔄 Setting default quantity for existing equipment...")
                Equipment.query.update({Equipment.quantity_owned: 1})
                db.session.commit()
                print("✅ Default quantities set!")
            except Exception as e:
                print(f"⚠️  Could not add quantity_owned column: {e}")
                print("   This might be okay if the column already exists.")
        else:
            print("✓ quantity_owned column already exists")
        
        print("\n✅ Migration complete! All new features are ready to use.")
        print("\nNew features added:")
        print("  • Hired Equipment tracking with return dates")
        print("  • Pre-return checklists")
        print("  • Bulk delete for hired equipment")
        print("  • CSV import for hired equipment")
        print("  • Quantity tracking for owned equipment")
        print("  • Over-allocation warnings in pick lists")

if __name__ == '__main__':
    migrate_database()