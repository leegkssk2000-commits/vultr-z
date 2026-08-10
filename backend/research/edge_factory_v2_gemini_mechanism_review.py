from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from backend.tools.zel_manual_multiaxis_gemini_v2 import call_generate, parse_json

ALLOWED_DECISIONS={"PASS_TO_T1_REVIEW","HOLD","REJECT"}
SAFE={
    "research_only":True,
    "promotion_authority":False,
    "protected_mutations":0,
    "execution_allowed":False,
    "execution_authority":"NONE",
    "order_authority":"BLOCKED",
    "runtime_bound":False,
    "rule_change_authority":False,
    "threshold_change_authority":False,
}

def canonical(v:Any)->str:
    return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)

def sha(v:str)->str:
    return hashlib.sha256(v.encode()).hexdigest()

def write(path:Path,v:dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)+'\n')

def contract()->dict[str,Any]:
    return {
        "decision":"PASS_TO_T1_REVIEW|HOLD|REJECT",
        "mechanism_plausible":True,
        "aggregation_is_single_axis":True,
        "overfit_risk":"LOW|MEDIUM|HIGH",
        "confounders":["short label"],
        "fatal_blockers":["short code"],
        "reason":"one concise paragraph",
    }

def validate(r:Any)->dict[str,Any]:
    expected={"decision","mechanism_plausible","aggregation_is_single_axis","overfit_risk","confounders","fatal_blockers","reason"}
    if not isinstance(r,dict) or set(r)!=expected: raise ValueError('GEMINI_REVIEW_SHAPE')
    if r['decision'] not in ALLOWED_DECISIONS: raise ValueError('GEMINI_REVIEW_DECISION')
    if not isinstance(r['mechanism_plausible'],bool): raise ValueError('GEMINI_MECHANISM_BOOL')
    if not isinstance(r['aggregation_is_single_axis'],bool): raise ValueError('GEMINI_AXIS_BOOL')
    if r['overfit_risk'] not in {'LOW','MEDIUM','HIGH'}: raise ValueError('GEMINI_OVERFIT')
    for k in ('confounders','fatal_blockers'):
        if not isinstance(r[k],list) or not all(isinstance(x,str) for x in r[k]): raise ValueError(f'GEMINI_{k.upper()}')
    if not isinstance(r['reason'],str) or not r['reason'].strip(): raise ValueError('GEMINI_REASON')
    if r['decision']=='PASS_TO_T1_REVIEW' and (not r['mechanism_plausible'] or not r['aggregation_is_single_axis'] or r['fatal_blockers']):
        raise ValueError('GEMINI_PASS_CONTRADICTION')
    return r

def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    payload=json.loads(a.input.read_text())
    key=os.environ.get('GEMINI_API_KEY','').strip()
    base={"version":"ZEL_EDGE_FACTORY_V2_GEMINI_MECHANISM_REVIEW_V1","provider":"google_gemini","input_sha":sha(canonical(payload)),**SAFE}
    try:
        if not key: raise RuntimeError('HOLD_GEMINI_API_KEY_MISSING')
        prompt=(
            "You are a skeptical quantitative trading research reviewer. You have no authority to change rules, thresholds, parameters, select a strategy, or approve live trading. "
            "Review only whether the already-frozen candidate is logically eligible for ONE untouched final holdout test. "
            "The underlying signal is frozen; equal-weight aggregation is the only new axis. Explicitly examine common-volatility beta, bull-regime coincidence, correlated event days, selection-after-seeing-two-windows, execution aggregation semantics, and causal lookahead. "
            "Do not propose any new threshold, filter, holding period, exit, symbol subset, or parameter. "
            "PASS_TO_T1_REVIEW means only 'reasonable to test once on untouched T1'; it is not evidence of profitability or promotion. Return strict JSON only.\n"
            f"OUTPUT_SCHEMA={canonical(contract())}\nINPUT={canonical(payload)}"
        )
        model,text=call_generate(key,prompt,source=None,max_output_tokens=1200)
        review=validate(parse_json(text))
        artifact={**base,"status":"PASS_GEMINI_MECHANISM_REVIEW_CONNECTION","actual_model":model,"prompt_sha":sha(prompt),"response_sha":sha(text),"review":review,"blocker_code":None}
    except Exception as exc:
        artifact={**base,"status":"HOLD_GEMINI_MECHANISM_REVIEW","actual_model":None,"prompt_sha":None,"response_sha":None,"review":{"decision":"HOLD","mechanism_plausible":False,"aggregation_is_single_axis":False,"overfit_risk":"HIGH","confounders":[],"fatal_blockers":[str(exc)[:500]],"reason":"Gemini mechanism review did not complete under the frozen contract."},"blocker_code":str(exc)[:500]}
    write(a.output,artifact)
    print(json.dumps({"status":artifact['status'],"decision":artifact['review']['decision'],"model":artifact['actual_model'],"blocker":artifact['blocker_code']},sort_keys=True))
    return 0

if __name__=='__main__':raise SystemExit(main())
