"""routes package — register all blueprints in register_blueprints()."""

"""routes package — register all blueprints in register_blueprints()."""

def register_blueprints(app):
    from routes.auth             import auth_bp
    from routes.two_factor_auth  import tfa_bp
    from routes.oauth            import oauth_bp
    from routes.equipment        import equipment_bp
    from routes.events           import events_bp
    from routes.crew             import crew_bp
    from routes.shifts           import shifts_bp
    from routes.cast             import cast_bp
    from routes.admin            import admin_bp
    from routes.picklist         import picklist_bp
    from routes.stage_designer   import stage_designer_bp
    from routes.discord          import discord_bp
    from routes.profile          import profile_bp
    from routes.calendar         import calendar_bp
    from routes.rocketchat       import rocketchat_bp
    from routes.todos            import todos_bp
    from routes.hired_equipment  import hired_equipment_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(tfa_bp)
    app.register_blueprint(oauth_bp)
    app.register_blueprint(equipment_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(crew_bp)
    app.register_blueprint(shifts_bp)
    app.register_blueprint(cast_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(picklist_bp)
    app.register_blueprint(stage_designer_bp)
    app.register_blueprint(discord_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(rocketchat_bp)
    app.register_blueprint(todos_bp)
    app.register_blueprint(hired_equipment_bp)