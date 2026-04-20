from engine.registry import get, load_auto
load_auto()

def route(name: str, **kwargs):
    fn = get(name)
    if not fn:
        raise ValueError(f"strategy not found: {name}")
    return fn(**kwargs)
