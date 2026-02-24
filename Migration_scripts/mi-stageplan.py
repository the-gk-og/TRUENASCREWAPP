#!/usr/bin/env python3
"""
Complete Migration Script for Stage Plan Designer
Run this with: python migrate_stage_designer.py
"""

import sys
import os

# Add the parent directory to the path so we can import app
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db

def migrate():
    with app.app_context():
        print("\n" + "="*80)
        print("🎨 STAGE PLAN DESIGNER - DATABASE MIGRATION")
        print("="*80 + "\n")
        
        try:
            # Import models to ensure they're registered
            from app import StagePlanTemplate, StagePlanDesign, StagePlanObject
            
            print("✓ Models imported successfully\n")
            
            # Create all tables
            print("📦 Creating database tables...")
            db.create_all()
            print("✓ Tables created successfully!\n")
            
            # Check if tables exist
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            
            print("📋 Checking tables:")
            required_tables = ['stage_plan_template', 'stage_plan_design', 'stage_plan_object']
            for table in required_tables:
                if table in tables:
                    print(f"  ✓ {table}")
                else:
                    print(f"  ✗ {table} - NOT FOUND!")
            print()
            
            # Add default objects
            print("🎨 Adding default stage objects...")
            
            default_objects = [
                {
                    'name': 'Speaker',
                    'category': 'Audio',
                    'image_data': 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgZmlsbD0iIzMzMyIgcng9IjEwIi8+PGNpcmNsZSBjeD0iNTAiIGN5PSI1MCIgcj0iMzAiIGZpbGw9IiM2NjYiLz48Y2lyY2xlIGN4PSI1MCIgY3k9IjUwIiByPSIxNSIgZmlsbD0iIzk5OSIvPjwvc3ZnPg==',
                    'default_width': 80,
                    'default_height': 80
                },
                {
                    'name': 'Microphone',
                    'category': 'Audio',
                    'image_data': 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNTAiIGhlaWdodD0iMTAwIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjxyZWN0IHg9IjE1IiB5PSIxMCIgd2lkdGg9IjIwIiBoZWlnaHQ9IjMwIiBmaWxsPSIjMzMzIiByeD0iMTAiLz48Y2lyY2xlIGN4PSIyNSIgY3k9IjUiIHI9IjEwIiBmaWxsPSIjNjY2Ii8+PHJlY3QgeD0iMjIiIHk9IjQwIiB3aWR0aD0iNiIgaGVpZ2h0PSI1MCIgZmlsbD0iIzMzMyIvPjxjaXJjbGUgY3g9IjI1IiBjeT0iOTUiIHI9IjgiIGZpbGw9IiM2NjYiLz48L3N2Zz4=',
                    'default_width': 50,
                    'default_height': 100
                },
                {
                    'name': 'Spotlight',
                    'category': 'Lighting',
                    'image_data': 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZGVmcz48cmFkaWFsR3JhZGllbnQgaWQ9ImxpZ2h0Ij48c3RvcCBvZmZzZXQ9IjAlIiBzdG9wLWNvbG9yPSIjRkZGRkZGIi8+PHN0b3Agb2Zmc2V0PSI1MCUiIHN0b3AtY29sb3I9IiNGRkQ3MDAiLz48c3RvcCBvZmZzZXQ9IjEwMCUiIHN0b3AtY29sb3I9IiNGRjg4MDAiIHN0b3Atb3BhY2l0eT0iMC4zIi8+PC9yYWRpYWxHcmFkaWVudD48L2RlZnM+PGNpcmNsZSBjeD0iNTAiIGN5PSI1MCIgcj0iNDUiIGZpbGw9InVybCgjbGlnaHQpIi8+PGNpcmNsZSBjeD0iNTAiIGN5PSI1MCIgcj0iMjAiIGZpbGw9IiNGRkZGRkYiLz48L3N2Zz4=',
                    'default_width': 100,
                    'default_height': 100
                },
                {
                    'name': 'Chair',
                    'category': 'Furniture',
                    'image_data': 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAiIGhlaWdodD0iODAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHJlY3QgeD0iMTAiIHk9IjMwIiB3aWR0aD0iNDAiIGhlaWdodD0iNSIgZmlsbD0iIzY2NiIgcng9IjIiLz48cmVjdCB4PSIxMCIgeT0iNSIgd2lkdGg9IjQwIiBoZWlnaHQ9IjI4IiBmaWxsPSIjODg4IiByeD0iMyIvPjxyZWN0IHg9IjEyIiB5PSIzNSIgd2lkdGg9IjUiIGhlaWdodD0iNDAiIGZpbGw9IiM2NjYiIHJ4PSIyIi8+PHJlY3QgeD0iNDMiIHk9IjM1IiB3aWR0aD0iNSIgaGVpZ2h0PSI0MCIgZmlsbD0iIzY2NiIgcng9IjIiLz48L3N2Zz4=',
                    'default_width': 60,
                    'default_height': 80
                },
                {
                    'name': 'Table',
                    'category': 'Furniture',
                    'image_data': 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTUwIiBoZWlnaHQ9IjEwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB4PSIxMCIgeT0iMzAiIHdpZHRoPSIxMzAiIGhlaWdodD0iMTAiIGZpbGw9IiM4ODgiIHJ4PSIzIi8+PHJlY3QgeD0iMjAiIHk9IjQwIiB3aWR0aD0iOCIgaGVpZ2h0PSI1MCIgZmlsbD0iIzY2NiIgcng9IjIiLz48cmVjdCB4PSIxMjIiIHk9IjQwIiB3aWR0aD0iOCIgaGVpZ2h0PSI1MCIgZmlsbD0iIzY2NiIgcng9IjIiLz48L3N2Zz4=',
                    'default_width': 150,
                    'default_height': 100
                },
                {
                    'name': 'Platform',
                    'category': 'Structure',
                    'image_data': 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAwIiBoZWlnaHQ9IjEwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMjAwIiBoZWlnaHQ9IjEwMCIgZmlsbD0iIzk5OSIgc3Ryb2tlPSIjMzMzIiBzdHJva2Utd2lkdGg9IjMiIHJ4PSI1Ii8+PGxpbmUgeDE9IjAiIHkxPSIyMCIgeDI9IjIwMCIgeTI9IjIwIiBzdHJva2U9IiM3NzciIHN0cm9rZS13aWR0aD0iMSIvPjxsaW5lIHgxPSIwIiB5MT0iNDAiIHgyPSIyMDAiIHkyPSI0MCIgc3Ryb2tlPSIjNzc3IiBzdHJva2Utd2lkdGg9IjEiLz48bGluZSB4MT0iMCIgeTE9IjYwIiB4Mj0iMjAwIiB5Mj0iNjAiIHN0cm9rZT0iIzc3NyIgc3Ryb2tlLXdpZHRoPSIxIi8+PGxpbmUgeDE9IjAiIHkxPSI4MCIgeDI9IjIwMCIgeTI9IjgwIiBzdHJva2U9IiM3NzciIHN0cm9rZS13aWR0aD0iMSIvPjwvc3ZnPg==',
                    'default_width': 200,
                    'default_height': 100
                },
                {
                    'name': 'Curtain',
                    'category': 'Structure',
                    'image_data': 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAwIiBoZWlnaHQ9IjE1MCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZGVmcz48bGluZWFyR3JhZGllbnQgaWQ9ImN1cnRhaW4iIHgxPSIwJSIgeTE9IjAlIiB4Mj0iMTAwJSIgeTI9IjAlIj48c3RvcCBvZmZzZXQ9IjAlIiBzdG9wLWNvbG9yPSIjYzkzNDJkIi8+PHN0b3Agb2Zmc2V0PSI1MCUiIHN0b3AtY29sb3I9IiNhNjI4MjEiLz48c3RvcCBvZmZzZXQ9IjEwMCUiIHN0b3AtY29sb3I9IiNjOTM0MmQiLz48L2xpbmVhckdyYWRpZW50PjwvZGVmcz48cmVjdCB3aWR0aD0iMjAwIiBoZWlnaHQ9IjE1MCIgZmlsbD0idXJsKCNjdXJ0YWluKSIvPjxwYXRoIGQ9Ik0gMCAwIFEgMjUgMTUgNTAgMCBUIDEwMCAwIFQgMTUwIDAgVCAyMDAgMCIgc3Ryb2tlPSIjOGExOTE0IiBmaWxsPSJub25lIiBzdHJva2Utd2lkdGg9IjMiLz48L3N2Zz4=',
                    'default_width': 200,
                    'default_height': 150
                },
                {
                    'name': 'Drum Kit',
                    'category': 'Props',
                    'image_data': 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIwIiBoZWlnaHQ9IjEwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48Y2lyY2xlIGN4PSI2MCIgY3k9IjUwIiByPSIzNSIgZmlsbD0iIzMzMyIgc3Ryb2tlPSIjNjY2IiBzdHJva2Utd2lkdGg9IjMiLz48Y2lyY2xlIGN4PSI2MCIgY3k9IjUwIiByPSIyOCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjOTk5IiBzdHJva2Utd2lkdGg9IjIiLz48Y2lyY2xlIGN4PSIzMCIgY3k9IjMwIiByPSIyMCIgZmlsbD0iIzQ0NCIgc3Ryb2tlPSIjNzc3IiBzdHJva2Utd2lkdGg9IjIiLz48Y2lyY2xlIGN4PSI5MCIgY3k9IjMwIiByPSIyMCIgZmlsbD0iIzQ0NCIgc3Ryb2tlPSIjNzc3IiBzdHJva2Utd2lkdGg9IjIiLz48L3N2Zz4=',
                    'default_width': 120,
                    'default_height': 100
                }
            ]
            
            added_count = 0
            for obj_data in default_objects:
                # Check if object already exists
                existing = StagePlanObject.query.filter_by(name=obj_data['name']).first()
                if not existing:
                    obj = StagePlanObject(
                        name=obj_data['name'],
                        category=obj_data['category'],
                        image_data=obj_data['image_data'],
                        default_width=obj_data['default_width'],
                        default_height=obj_data['default_height'],
                        created_by='System',
                        is_public=True
                    )
                    db.session.add(obj)
                    added_count += 1
                    print(f"  ✓ {obj_data['name']} ({obj_data['category']})")
                else:
                    print(f"  ⊘ {obj_data['name']} (already exists)")
            
            db.session.commit()
            
            # Final count
            total_objects = StagePlanObject.query.count()
            total_designs = StagePlanDesign.query.count()
            total_templates = StagePlanTemplate.query.count()
            
            print("\n" + "="*80)
            print("✅ MIGRATION COMPLETED SUCCESSFULLY!")
            print("="*80)
            print(f"\n📊 Database Summary:")
            print(f"  • Objects in library: {total_objects}")
            print(f"  • Saved designs: {total_designs}")
            print(f"  • Templates: {total_templates}")
            print(f"  • New objects added: {added_count}")
            
            print("\n🎨 Stage Plan Designer is ready to use!")
            print("   Access it at: http://localhost:5000/stage-designer")
            
            print("\n📝 Next Steps:")
            print("   1. Restart your Flask app: python app.py")
            print("   2. Navigate to Stage Plan Designer in your app menu")
            print("   3. Start creating stage plans!")
            print("\n" + "="*80 + "\n")
            
        except ImportError as e:
            print("\n❌ ERROR: Could not import Stage Plan Designer models!")
            print(f"   {str(e)}")
            print("\n📝 Make sure you have added the THREE model classes to app.py:")
            print("   - StagePlanTemplate")
            print("   - StagePlanDesign")
            print("   - StagePlanObject")
            print("\n   These should be added after your other models (around line 150)")
            print("\n" + "="*80 + "\n")
            sys.exit(1)
            
        except Exception as e:
            print("\n❌ MIGRATION FAILED!")
            print(f"   Error: {str(e)}")
            print("\n🔍 Debugging info:")
            import traceback
            traceback.print_exc()
            print("\n" + "="*80 + "\n")
            db.session.rollback()
            sys.exit(1)

if __name__ == '__main__':
    migrate()