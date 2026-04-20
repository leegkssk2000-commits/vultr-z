import yaml, os
CFG_E = "/home/z/z/config/ensembles.yml"
def load():
    with open(CFG_E,"r") as f: return yaml.safe_load(f)
def select(regime="bull"):
    cfg = load()
    ens = cfg.get("ensembles", {})
    return ens.get(regime, {"long":[], "short":[]})