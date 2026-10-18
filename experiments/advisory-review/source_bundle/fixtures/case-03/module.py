def select_ready(tasks):
    ready = [t for t in tasks if t['ready']]
    if not ready:
        return None
    return sorted(ready, key=lambda t: -t['priority'])[0]
