from pathlib import Path

def resolve_repo_path(root: str, relative: str) -> Path:
    base = Path(root).resolve()
    target = (base / relative).resolve()
    if not str(target).startswith(str(base)):
        raise ValueError("outside repository")
    return target
