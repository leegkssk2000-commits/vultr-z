import numpy as np, pandas as pd, time
def _nz(x,a=1e-9): return np.maximum(x,a)
def _pct_rank(s, win=200):
    r = (pd.Series(s).rolling(win).rank(pct=True)).to_numpy()
    r[np.isnan(r)] = 0.5; return r
def regime_scores(df: pd.DataFrame)->dict:
    # df: columns=[open,high,low,close,volume], index=time
    c=df['close'].to_numpy(); h=df['high'].to_numpy(); l=df['low'].to_numpy(); v=df['volume'].to_numpy()
    ret = np.diff(np.log(_nz(c))); ret = np.r_[0,ret]
    atr = (pd.Series(h-l).rolling(14).mean()/pd.Series(c).rolling(14).mean()).to_numpy()
    atr_p = _pct_rank(atr,200) # 변동성 분위
    mom = (pd.Series(c).pct_change(24).rolling(24).mean()).to_numpy()
    mom_s = (mom - np.nanmean(mom))/ (np.nanstd(mom)+1e-9) # 모멘텀 z
    vol_s = (pd.Series(v).rolling(48).apply(lambda x:(x[-1]-np.mean(x))/(_nz(np.std(x))), raw=True)).to_numpy()
    brk = (pd.Series(c).rolling(24).max()-pd.Series(c).rolling(24).min())/_nz(pd.Series(c).rolling(24).mean())
    brk_p = _pct_rank(brk,200)
    trend = _pct_rank(pd.Series(c).rolling(48).apply(lambda x: np.polyfit(np.arange(len(x)), x, 1)[0], raw=True), 200)
    # 0..1 정규화
    def clamp01(x): 
        x=np.nan_to_num(x, nan=0.5); return np.clip((x - np.min(x[-200:]))/_nz(np.max(x[-200:])-np.min(x[-200:])),0,1)
    out = {
        "vol": float(clamp01(atr_p)[-1]),
        "momentum": float(clamp01(mom_s)[-1]),
        "liquidity": float(clamp01(vol_s)[-1]),
        "breakout": float(clamp01(brk_p)[-1]),
        "trend": float(clamp01(trend)[-1]),
        "ts": int(time.time())
    }
    return out