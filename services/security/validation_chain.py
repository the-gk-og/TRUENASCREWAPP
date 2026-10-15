"""Input Validation and Sanitization Chain"""
import re
from services.security.security_utils import detect_malicious_patterns, sanitize_input, validate_email


class ValidationChain:
    """Multi-step validation chain"""
    
    def __init__(self):
        self.validators = []
        self.sanitizers = []
    
    def add_validator(self, validator_func, name=None):
        """Add a validator to the chain"""
        self.validators.append({
            'func': validator_func,
            'name': name or validator_func.__name__
        })
        return self
    
    def add_sanitizer(self, sanitizer_func, name=None):
        """Add a sanitizer to the chain"""
        self.sanitizers.append({
            'func': sanitizer_func,
            'name': name or sanitizer_func.__name__
        })
        return self
    
    def validate(self, data):
        """Run all validators"""
        errors = []
        for validator in self.validators:
            result = validator['func'](data)
            if result is not True:
                errors.append({
                    'validator': validator['name'],
                    'error': result if isinstance(result, str) else 'Validation failed'
                })
        return len(errors) == 0, errors
    
    def sanitize(self, data):
        """Run all sanitizers"""
        for sanitizer in self.sanitizers:
            data = sanitizer['func'](data)
        return data


# Pre-built validation chains

def create_email_validation_chain():
    """Email field validation"""
    chain = ValidationChain()
    chain.add_validator(lambda x: len(x) > 0 or 'Email cannot be empty')
    chain.add_validator(lambda x: len(x) <= 255 or 'Email too long')
    chain.add_validator(lambda x: validate_email(x) or 'Invalid email format')
    chain.add_sanitizer(lambda x: sanitize_input(x, allow_html=False))
    return chain


def create_username_validation_chain():
    """Username field validation"""
    chain = ValidationChain()
    chain.add_validator(lambda x: len(x) >= 3 or 'Username must be at least 3 characters')
    chain.add_validator(lambda x: len(x) <= 50 or 'Username too long')
    chain.add_validator(lambda x: re.match(r'^[a-zA-Z0-9_-]+$', x) or 'Username contains invalid characters')
    chain.add_validator(lambda x: len(detect_malicious_patterns(x)) == 0 or 'Username contains suspicious patterns')
    chain.add_sanitizer(lambda x: sanitize_input(x, allow_html=False))
    return chain


def create_message_validation_chain():
    """Message/text field validation"""
    chain = ValidationChain()
    chain.add_validator(lambda x: len(x) > 0 or 'Message cannot be empty')
    chain.add_validator(lambda x: len(x) <= 5000 or 'Message too long')
    chain.add_validator(lambda x: len(detect_malicious_patterns(x)) == 0 or 'Message contains suspicious patterns')
    chain.add_sanitizer(lambda x: sanitize_input(x, allow_html=False))
    return chain


def create_url_validation_chain():
    """URL field validation"""
    chain = ValidationChain()
    chain.add_validator(lambda x: len(x) > 0 or 'URL cannot be empty')
    chain.add_validator(lambda x: len(x) <= 1000 or 'URL too long')
    chain.add_validator(lambda x: re.match(r'^https?://', x) or 'URL must start with http:// or https://')
    chain.add_validator(lambda x: len(detect_malicious_patterns(x)) == 0 or 'URL contains suspicious patterns')
    chain.add_sanitizer(lambda x: sanitize_input(x, allow_html=False))
    return chain


def create_phone_validation_chain():
    """Phone number validation"""
    chain = ValidationChain()
    chain.add_validator(lambda x: len(x) > 0 or 'Phone cannot be empty')
    chain.add_validator(lambda x: len(x) <= 20 or 'Phone too long')
    chain.add_validator(lambda x: re.match(r'^[\d\s\-\+\(\)]+$', x) or 'Invalid phone format')
    chain.add_sanitizer(lambda x: sanitize_input(x, allow_html=False))
    return chain


# Validation presets
VALIDATION_PRESETS = {
    'email': create_email_validation_chain,
    'username': create_username_validation_chain,
    'message': create_message_validation_chain,
    'url': create_url_validation_chain,
    'phone': create_phone_validation_chain,
}


def validate_and_sanitize(field_type, value):
    """Quick validation and sanitization using presets"""
    if field_type not in VALIDATION_PRESETS:
        raise ValueError(f'Unknown field type: {field_type}')
    
    chain = VALIDATION_PRESETS[field_type]()
    is_valid, errors = chain.validate(value)
    
    if not is_valid:
        return None, errors
    
    sanitized = chain.sanitize(value)
    return sanitized, []
