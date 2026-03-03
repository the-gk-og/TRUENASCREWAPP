"""
constants.py
============
App-wide constants shared across routes and services.
"""

DEFAULT_ORG = {
    'name':            'ShowWise',
    'slug':            'showwise',
    'tagline':         'Crew Management',
    'primary_color':   '#6366f1',
    'secondary_color': '#ec4899',
    'logo':            '',
    'website':         'https://sfx-crew.com',
}

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

USER_ROLES = ('crew', 'staff', 'cast')

SHIFT_STATUSES = ('pending', 'accepted', 'rejected', 'confirmed')

RECURRENCE_PATTERNS = ('daily', 'weekly', 'biweekly', 'monthly', 'yearly')
