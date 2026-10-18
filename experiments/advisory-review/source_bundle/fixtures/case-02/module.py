SENSITIVE = {'token','api_key','password','authorization'}

def sanitize_trace(value):
    if isinstance(value, dict):
        return {k: v for k, v in value.items() if str(k).lower() not in SENSITIVE}
    if isinstance(value, list):
        return [sanitize_trace(v) for v in value]
    return value
