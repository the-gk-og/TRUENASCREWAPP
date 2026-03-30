"""routes/stage_designer.py — Stage plan designer, templates, objects."""

import os, json, base64
from datetime import datetime

from flask import (
    Blueprint, render_template, request, jsonify,
    redirect, url_for, send_from_directory,
)
from flask_login import login_required, current_user

from extensions import db
from models import (
    Event, StagePlan, StagePlanDesign, StagePlanTemplate, StagePlanObject, StagePlanCollection,
)
from decorators import crew_required

stage_designer_bp = Blueprint('stage_designer', __name__)
UPLOAD_FOLDER = 'uploads'


def _save_thumbnail(name: str, b64: str) -> str | None:
    try:
        raw      = b64.split(',')[1] if ',' in b64 else b64
        data     = base64.b64decode(raw)
        safe     = ''.join(c if c.isalnum() or c in ' -_' else '_' for c in name)
        filename = f"designer_thumb_{int(datetime.now().timestamp())}_{safe}.png"
        with open(os.path.join(UPLOAD_FOLDER, filename), 'wb') as f:
            f.write(data)
        return filename
    except Exception as exc:
        print(f"⚠️  Could not save thumbnail: {exc}")
        return None


@stage_designer_bp.route('/stage-designer')
@login_required
@crew_required
def stage_designer():
    events    = Event.query.order_by(Event.event_date.desc()).all()
    templates = StagePlanTemplate.query.filter(
        (StagePlanTemplate.is_public == True) |
        (StagePlanTemplate.created_by == current_user.username)
    ).order_by(StagePlanTemplate.created_at.desc()).all()
    objects = StagePlanObject.query.filter(
        (StagePlanObject.is_public == True) |
        (StagePlanObject.created_by == current_user.username)
    ).order_by(StagePlanObject.category, StagePlanObject.name).all()
    return render_template('crew/stage_designer.html',
                           events=events, templates=templates, objects=objects)


# Designs
@stage_designer_bp.route('/stage-designer/design', methods=['POST'])
@login_required
@crew_required
def create_stage_design():
    try:
        data      = request.json
        thumbnail = _save_thumbnail(data['name'], data['thumbnail']) if data.get('thumbnail') else None
        design    = StagePlanDesign(
            name=data['name'], design_data=json.dumps(data['design_data']),
            thumbnail=thumbnail, event_id=data.get('event_id'),
            created_by=current_user.username,
        )
        db.session.add(design)
        db.session.flush()
        if data.get('save_to_stageplans'):
            db.session.add(StagePlan(
                title=data['name'],
                filename=thumbnail or f"designer_{design.id}.json",
                uploaded_by=current_user.username, event_id=data.get('event_id'),
            ))
        db.session.commit()
        return jsonify({'success': True, 'design_id': design.id})
    except Exception as exc:
        db.session.rollback()
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(exc)}), 500


@stage_designer_bp.route('/stage-designer/design/<int:id>', methods=['PUT'])
@login_required
@crew_required
def update_stage_design(id):
    try:
        design    = StagePlanDesign.query.get_or_404(id)
        data      = request.json
        thumbnail = design.thumbnail
        if data.get('thumbnail'):
            if thumbnail and os.path.exists(os.path.join(UPLOAD_FOLDER, thumbnail)):
                try: os.remove(os.path.join(UPLOAD_FOLDER, thumbnail))
                except Exception: pass
            thumbnail = _save_thumbnail(data['name'], data['thumbnail'])
        design.name        = data.get('name', design.name)
        design.design_data = json.dumps(data['design_data'])
        design.thumbnail   = thumbnail
        design.event_id    = data.get('event_id')
        design.updated_at  = datetime.utcnow()
        db.session.commit()
        return jsonify({'success': True, 'design_id': design.id})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(exc)}), 500


@stage_designer_bp.route('/stage-designer/designs')
@login_required
@crew_required
def list_stage_designs():
    designs = StagePlanDesign.query.order_by(StagePlanDesign.updated_at.desc()).all()
    return jsonify([{
        'id': d.id, 'name': d.name, 'event_id': d.event_id,
        'event_name': d.event.title if d.event else None,
        'thumbnail': url_for('uploaded_file', filename=d.thumbnail) if d.thumbnail else None,
        'created_by': d.created_by,
        'created_at': d.created_at.isoformat(), 'updated_at': d.updated_at.isoformat(),
    } for d in designs])


@stage_designer_bp.route('/stage-designer/design/<int:id>/data')
@login_required
@crew_required
def get_stage_design(id):
    design = StagePlanDesign.query.get_or_404(id)
    return jsonify({'id': design.id, 'name': design.name,
                    'design_data': json.loads(design.design_data),
                    'event_id': design.event_id, 'thumbnail': design.thumbnail})


@stage_designer_bp.route('/stage-designer/design/<int:id>', methods=['DELETE'])
@login_required
@crew_required
def delete_stage_design(id):
    design = StagePlanDesign.query.get_or_404(id)
    try:
        db.session.delete(design)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(exc)}), 500


# Templates
@stage_designer_bp.route('/stage-designer/template', methods=['POST'])
@login_required
@crew_required
def save_stage_template():
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Admin access required'}), 403
    try:
        data = request.json
        template = StagePlanTemplate(
            name=data['name'], description=data.get('description', ''),
            design_data=json.dumps(data['design_data']),
            thumbnail=data.get('thumbnail'), created_by=current_user.username,
            is_public=data.get('is_public', True),
        )
        db.session.add(template)
        db.session.commit()
        return jsonify({'success': True, 'id': template.id})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(exc)}), 500


@stage_designer_bp.route('/stage-designer/templates')
@login_required
@crew_required
def get_stage_templates():
    templates = StagePlanTemplate.query.filter(
        (StagePlanTemplate.is_public == True) |
        (StagePlanTemplate.created_by == current_user.username)
    ).order_by(StagePlanTemplate.created_at.desc()).all()
    return jsonify([{
        'id': t.id, 'name': t.name, 'description': t.description,
        'thumbnail': url_for('uploaded_file', filename=t.thumbnail) if t.thumbnail else None,
        'created_by': t.created_by, 'created_at': t.created_at.isoformat(),
    } for t in templates])


@stage_designer_bp.route('/stage-designer/template/<int:id>/data')
@login_required
@crew_required
def get_stage_template(id):
    t = StagePlanTemplate.query.get_or_404(id)
    return jsonify({'id': t.id, 'name': t.name, 'design_data': json.loads(t.design_data)})


@stage_designer_bp.route('/stage-designer/template/<int:id>', methods=['DELETE'])
@login_required
@crew_required
def delete_stage_template(id):
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Admin access required'}), 403
    t = StagePlanTemplate.query.get_or_404(id)
    try:
        db.session.delete(t)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(exc)}), 500


# Objects
@stage_designer_bp.route('/stage-designer/object', methods=['POST'])
@login_required
@crew_required
def upload_stage_object():
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Admin access required'}), 403
    try:
        data = request.json
        obj  = StagePlanObject(
            name=data['name'], category=data.get('category', 'Uncategorized'),
            image_data=data['image_data'],
            default_width=data.get('default_width', 100),
            default_height=data.get('default_height', 100),
            created_by=current_user.username, is_public=data.get('is_public', True),
        )
        db.session.add(obj)
        db.session.commit()
        return jsonify({'success': True, 'id': obj.id})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(exc)}), 500


@stage_designer_bp.route('/stage-designer/objects')
@login_required
@crew_required
def get_stage_objects():
    objects = StagePlanObject.query.filter(
        (StagePlanObject.is_public == True) |
        (StagePlanObject.created_by == current_user.username)
    ).order_by(StagePlanObject.category, StagePlanObject.name).all()
    return jsonify([{
        'id': o.id, 'name': o.name, 'category': o.category,
        'image_data': o.image_data, 'default_width': o.default_width,
        'default_height': o.default_height,
    } for o in objects])


@stage_designer_bp.route('/stage-designer/objects/<int:id>', methods=['DELETE'])
@login_required
@crew_required
def delete_stage_object(id):
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Admin access required'}), 403
    obj = StagePlanObject.query.get_or_404(id)
    try:
        db.session.delete(obj)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(exc)}), 500


# Stage plans (upload)
@stage_designer_bp.route('/stageplans')
@login_required
@crew_required
def stageplans():
    event_id = request.args.get('event_id')
    event    = Event.query.get(event_id) if event_id else None
    plans    = StagePlan.query.filter_by(event_id=event_id, is_archived=False).all() if event_id else StagePlan.query.filter_by(is_archived=False).all()
    collections = StagePlanCollection.query.filter_by(event_id=event_id, is_archived=False).all() if event_id else []
    events   = Event.query.order_by(Event.event_date.desc()).all()
    return render_template('/crew/stageplans.html', plans=plans, events=events, current_event=event, collections=collections)


@stage_designer_bp.route('/stageplans/upload', methods=['POST'])
@login_required
@crew_required
def upload_stageplan():
    from werkzeug.utils import secure_filename
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secure_filename(file.filename)}"
    file.save(os.path.join(UPLOAD_FOLDER, filename))
    collection_id = request.form.get('collection_id')
    plan = StagePlan(title=request.form.get('title', filename), filename=filename,
                     uploaded_by=current_user.username, event_id=request.form.get('event_id'),
                     collection_id=collection_id if collection_id else None)
    db.session.add(plan)
    db.session.commit()
    return jsonify({'success': True, 'id': plan.id})


@stage_designer_bp.route('/uploads/<filename>')
@login_required
@crew_required
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@stage_designer_bp.route('/stageplans/delete/<int:id>', methods=['DELETE'])
@login_required
@crew_required
def delete_stageplan(id):
    plan = StagePlan.query.get_or_404(id)
    path = os.path.join(UPLOAD_FOLDER, plan.filename)
    if os.path.exists(path):
        os.remove(path)
    db.session.delete(plan)
    db.session.commit()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Stage Plan Collections (Multiple Plans per Event)
# ---------------------------------------------------------------------------

@stage_designer_bp.route('/stage-collections/create', methods=['POST'])
@login_required
@crew_required
def create_stage_collection():
    """Create a new stage plan collection."""
    data = request.json
    event_id = data.get('event_id')
    name = data.get('name', '')
    
    if not event_id or not name:
        return jsonify({'error': 'Event ID and name are required'}), 400
    
    Event.query.get_or_404(event_id)
    
    collection = StagePlanCollection(
        name=name,
        event_id=event_id,
        created_by=current_user.username
    )
    db.session.add(collection)
    db.session.commit()
    
    return jsonify({'success': True, 'id': collection.id, 'name': collection.name})


@stage_designer_bp.route('/stage-collections/<int:collection_id>/add-plan', methods=['POST'])
@login_required
@crew_required
def add_plan_to_collection(collection_id):
    """Add an existing stage plan to a collection."""
    collection = StagePlanCollection.query.get_or_404(collection_id)
    data = request.json
    plan_id = data.get('plan_id')
    
    if not plan_id:
        return jsonify({'error': 'Plan ID is required'}), 400
    
    plan = StagePlan.query.get_or_404(plan_id)
    plan.collection_id = collection_id
    db.session.commit()
    
    return jsonify({'success': True})


@stage_designer_bp.route('/stage-collections/<int:collection_id>/plans', methods=['GET'])
@login_required
@crew_required
def get_collection_plans(collection_id):
    """Get all plans in a collection."""
    collection = StagePlanCollection.query.get_or_404(collection_id)
    plans = StagePlan.query.filter_by(collection_id=collection_id, is_archived=False).all()
    
    return jsonify({
        'success': True,
        'collection': {
            'id': collection.id,
            'name': collection.name,
            'event_id': collection.event_id,
            'created_by': collection.created_by,
        },
        'plans': [
            {
                'id': plan.id,
                'title': plan.title,
                'filename': plan.filename,
                'uploaded_by': plan.uploaded_by,
                'created_at': plan.created_at.isoformat(),
            }
            for plan in plans
        ]
    })


@stage_designer_bp.route('/stage-collections/<int:collection_id>/delete', methods=['DELETE'])
@login_required
@crew_required
def delete_stage_collection(collection_id):
    """Delete a stage plan collection."""
    collection = StagePlanCollection.query.get_or_404(collection_id)
    db.session.delete(collection)
    db.session.commit()
    return jsonify({'success': True})


@stage_designer_bp.route('/stage-collections/<int:collection_id>/archive', methods=['PUT'])
@login_required
@crew_required
def archive_stage_collection(collection_id):
    """Archive a stage plan collection and its plans."""
    collection = StagePlanCollection.query.get_or_404(collection_id)
    collection.is_archived = not collection.is_archived
    
    # Also archive plans in this collection
    for plan in collection.plans:
        plan.is_archived = collection.is_archived
    
    db.session.commit()
    return jsonify({'success': True, 'is_archived': collection.is_archived})


@stage_designer_bp.route('/stageplans/<int:plan_id>/archive', methods=['PUT'])
@login_required
@crew_required
def archive_stage_plan(plan_id):
    """Archive a single stage plan."""
    plan = StagePlan.query.get_or_404(plan_id)
    plan.is_archived = not plan.is_archived
    db.session.commit()
    return jsonify({'success': True, 'is_archived': plan.is_archived})
