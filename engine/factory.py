import json, os, time, pathlib
CUR = "/home/z/z/config/current_strategy.json"
def apply(champ:dict):
    """champ: {"params":{...}, "blocks":{"entry":[], "filter":[], "exit":[], "risk":[]}}"""
    p=champ.get("params",{}); b=champ.get("blocks",{})
    # 환경키 반영(엔진에서 참조)
    env = {
      "FVG_MIN_PCT": p.get("FVG_MIN_PCT","5"),
      "FVG_USE_HALF": p.get("HALF","on"),
      "TF": p.get("TF","4h"),
      "ORB_WIN": p.get("ORB_WIN","30"),
      "RSI_LEN": p.get("RSI_LEN","14"),
      "MACD_FAST": p.get("MACD_FAST","12"),
      "MACD_SLOW": p.get("MACD_SLOW","26"),
      "VWAP_BAND": p.get("VWAP_BAND","1.0"),
      # 블록 on/off
      "BL_ENTRY": ",".join(b.get("entry",[])),
      "BL_FILTER": ",".join(b.get("filter",[])),
      "BL_EXIT": ",".join(b.get("exit",[])),
      "BL_RISK": ",".join(b.get("risk",[]))
    }
    for k,v in env.items(): os.environ[str(k)] = str(v)
    pathlib.Path(CUR).write_text(json.dumps({"ts":int(time.time()), **env}, ensure_ascii=False, indent=2))
    return env