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
    Event, StagePlan, StagePlanDesign, StagePlanTemplate, StagePlanObject,
)
from decorators import crew_required

stage_designer_bp = Blueprint('stage_designer', __name__)
UPLOAD_FOLDER = 'uploads'


def _save_thumbnail(name: str, b64: str) -> str | None:
    """Decode a PNG data-URI/base64 string into uploads/. Returns the filename or None."""
    try:
        raw  = b64.split(',', 1)[1] if ',' in b64 else b64
        data = base64.b64decode(raw, validate=True)
        if not data.startswith(b'\x89PNG'):
            raise ValueError('thumbnail is not a PNG image')
        safe     = ''.join(c if c.isalnum() or c in '-_' else '_' for c in name)[:60]
        filename = f"designer_thumb_{int(datetime.now().timestamp() * 1000)}_{safe}.png"
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        with open(os.path.join(UPLOAD_FOLDER, filename), 'wb') as f:
            f.write(data)
        return filename
    except Exception as exc:
        print(f"⚠️  Could not save thumbnail: {exc}")
        return None


def _to_int(value):
    """Form/JSON ids arrive as strings ('3') or ''/None; normalise to int or None."""
    try:
        return int(value) if value not in (None, '') else None
    except (TypeError, ValueError):
        return None


def _remove_upload(filename: str | None):
    if not filename:
        return
    path = os.path.join(UPLOAD_FOLDER, filename)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


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
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'success': False, 'error': 'A name is required.'}), 400
        if not data.get('design_data'):
            return jsonify({'success': False, 'error': 'No design data was received.'}), 400

        event_id  = _to_int(data.get('event_id'))
        thumbnail = _save_thumbnail(name, data['thumbnail']) if data.get('thumbnail') else None
        design    = StagePlanDesign(
            name=name, design_data=json.dumps(data['design_data']),
            thumbnail=thumbnail, event_id=event_id,
            created_by=current_user.username,
        )
        db.session.add(design)
        db.session.flush()
        # Only list on the Stage Plans page when there is a real image to show.
        if data.get('save_to_stageplans') and thumbnail:
            db.session.add(StagePlan(
                title=name, filename=thumbnail,
                uploaded_by=current_user.username, event_id=event_id,
            ))
        db.session.commit()
        return jsonify({'success': True, 'design_id': design.id,
                        'preview_saved': bool(thumbnail)})
    except Exception as exc:
        db.session.rollback()
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(exc)}), 500


@stage_designer_bp.route('/stage-designer/design/<int:id>', methods=['PUT'])
@login_required
@crew_required
def update_stage_design(id):
    old_thumbnail = None
    try:
        design = StagePlanDesign.query.get_or_404(id)
        data   = request.get_json(silent=True) or {}
        name   = (data.get('name') or design.name).strip()
        if not data.get('design_data'):
            return jsonify({'success': False, 'error': 'No design data was received.'}), 400

        event_id      = _to_int(data.get('event_id'))
        old_thumbnail = design.thumbnail
        new_thumbnail = _save_thumbnail(name, data['thumbnail']) if data.get('thumbnail') else None
        thumbnail     = new_thumbnail or old_thumbnail

        # Keep any Stage Plans entry that points at the old preview in sync,
        # otherwise it ends up referencing a file that no longer exists.
        linked = StagePlan.query.filter_by(filename=old_thumbnail).all() if old_thumbnail else []
        for plan in linked:
            if new_thumbnail:
                plan.filename = new_thumbnail
            plan.title    = name
            plan.event_id = event_id
        if data.get('save_to_stageplans') and thumbnail and not linked:
            db.session.add(StagePlan(
                title=name, filename=thumbnail,
                uploaded_by=current_user.username, event_id=event_id,
            ))

        design.name        = name
        design.design_data = json.dumps(data['design_data'])
        design.thumbnail   = thumbnail
        design.event_id    = event_id
        design.updated_at  = datetime.utcnow()
        db.session.commit()

        if new_thumbnail and old_thumbnail and new_thumbnail != old_thumbnail:
            _remove_upload(old_thumbnail)   # only after the DB no longer points at it
        return jsonify({'success': True, 'design_id': design.id,
                        'preview_saved': bool(new_thumbnail)})
    except Exception as exc:
        db.session.rollback()
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(exc)}), 500


@stage_designer_bp.route('/stage-designer/designs')
@login_required
@crew_required
def list_stage_designs():
    designs = StagePlanDesign.query.order_by(StagePlanDesign.updated_at.desc()).all()
    return jsonify([{
        'id': d.id, 'name': d.name, 'event_id': d.event_id,
        'event_name': d.event.title if d.event else None,
        'thumbnail': url_for('stage_designer.uploaded_file', filename=d.thumbnail) if d.thumbnail else None,
        'created_by': d.created_by,
        'created_at': d.created_at.isoformat(), 'updated_at': d.updated_at.isoformat(),
    } for d in designs])


@stage_designer_bp.route('/stage-designer/design/<int:id>/data')
@login_required
@crew_required
def get_stage_design(id):
    design = StagePlanDesign.query.get_or_404(id)
    try:
        design_data = json.loads(design.design_data)
    except (TypeError, ValueError):
        design_data = {}
    return jsonify({'id': design.id, 'name': design.name,
                    'design_data': design_data,
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
        'thumbnail': url_for('stage_designer.uploaded_file', filename=t.thumbnail) if t.thumbnail else None,
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
    plans    = StagePlan.query.filter_by(event_id=event_id).all() if event_id else StagePlan.query.all()
    events   = Event.query.order_by(Event.event_date.desc()).all()
    return render_template('/crew/stageplans.html', plans=plans, events=events, current_event=event)


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
    plan = StagePlan(title=request.form.get('title', filename), filename=filename,
                     uploaded_by=current_user.username, event_id=request.form.get('event_id'))
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
    filename = plan.filename
    db.session.delete(plan)
    db.session.commit()
    # A designer preview is shared with its saved design; keep the file in that case.
    in_use = (StagePlanDesign.query.filter_by(thumbnail=filename).first()
              or StagePlan.query.filter_by(filename=filename).first())
    if not in_use:
        _remove_upload(filename)
    return jsonify({'success': True})
