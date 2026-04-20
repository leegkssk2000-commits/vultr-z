#!/usr/bin/env python3
import os,time,json,subprocess,sys,math, pathlib
sys.path.append("/home/z/z"); from engine.alert import queue
ZH="/home/z/z"; DBW=f"{ZH}/db/z.sqlite-wal"; ST=f"{ZH}/logs/infra_state.json"
CPU=int(os.getenv("ALERT_UP_CPU","75")); RAM=int(os.getenv("ALERT_UP_RAM","70"))
DB=int(os.getenv("ALERT_UP_DB_MBPS","10")); API=int(os.getenv("ALERT_UP_API_MS","250"))
def cpu_pct():
    def snap():
        a=open("/proc/stat").readline().split()[1:]; a=list(map(int,a[:8])); u=sum(a[:7]); i=a[3]; return u,i
    u1,i1=snap(); time.sleep(1); u2,i2=snap()
    t=(u2+i2)-(u1+i1); busy=(u2-u1); return 100.0*busy/max(t,1)
def ram_pct():
    m=open("/proc/meminfo").read()
    tot=int(next(x for x in m.splitlines() if x.startswith("MemTotal")).split()[1])
    ava=int(next(x for x in m.splitlines() if x.startswith("MemAvailable")).split()[1])
    return 100.0*(1.0-ava/max(tot,1))
def swap_used():
    m=open("/proc/meminfo").read()
    st=int(next(x for x in m.splitlines() if x.startswith("SwapTotal")).split()[1])
    sf=int(next(x for x in m.splitlines() if x.startswith("SwapFree")).split()[1])
    return st>0 and sf<st
def wal_mbps():
    now=int(time.time()); sz=pathlib.Path(DBW).stat().st_size if pathlib.Path(DBW).exists() else 0
    st={"t":now,"sz":sz}
    if pathlib.Path(ST).exists():
        p=json.loads(open(ST).read()); dt=max(1,now-p["t"]); dsz=max(0,sz-p["sz"]); mbps=dsz/dt/1_000_000
    else: mbps=0.0
    open(ST,"w").write(json.dumps(st))
    return mbps
def api_ms():
    try:
        r=subprocess.run(["curl","-s","-o","/dev/null","-w","%{time_total}","http://127.0.0.1/api/health"],
                         capture_output=True, timeout=5)
        return float(r.stdout.decode().strip())*1000.0
    except: return 9999.0
def rate_hits():
    p="/var/log/nginx/error.log"
    try:
        r=subprocess.run(["tail","-n","300",p],capture_output=True, text=True)
        return sum(1 for L in r.stdout.splitlines() if "limiting requests" in L)
    except: return 0
def sev(hi): return "C" if hi else "M"
def main():
    c=cpu_pct(); r=ram_pct(); w=wal_mbps(); a=api_ms(); rl=rate_hits(); sw=swap_used()
    if c>=CPU: queue("SYS","infra","cpu_p95",f"{c:.0f}%",f"{CPU}%", sev(c>=CPU*1.1),"sys:","route_change")
    if r>=RAM or sw: queue("SYS","infra","ram_used",f"{r:.0f}%",f"{RAM}%", sev(r>=RAM*1.1 or sw),"sys:","reduce25")
    if w>=DB: queue("SYS","infra","db_wal_mbps",f"{w:.1f}MB/s",f"{DB}MB/s", sev(w>=DB*1.5),"sys:","route_change")
    if a>=API or rl>0: queue("SYS","infra","api_latency",f"{a:.0f}ms",f"{API}ms", sev(a>=API*2 or rl>10),"sys:","hold")
if __name__=="__main__": main()