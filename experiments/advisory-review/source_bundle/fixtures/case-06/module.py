_ALLOWED = {
    'CLAIMED': {'RUNNING'},
    'RUNNING': {'VERIFYING'},
    'VERIFYING': {'READY_TO_INTEGRATE'},
}

def validate_transition(current, expected, target):
    if current != expected or target not in _ALLOWED.get(current, set()):
        raise ValueError('invalid run transition')
    return target
