import os, subprocess, json, time
from engine.alert import queue
def check_and_trip():
    ms=float(subprocess.run(
        ["curl","-s","-o","/dev/null","-w","%{time_total}","http://127.0.0.1/api/health"],
        capture_output=True, timeout=5).stdout.decode() or 9.999)*1000
    err=0.0 # 필요시 Nginx 로그 파싱으로 대체
    if ms>float(os.getenv("SLO_API_MS","250")) or err>float(os.getenv("SLO_ERR_PCT","0.5")):
        os.environ["BREAKER"]="on"
        queue("SYS","infra","api_latency",f"{ms:.0f}ms",os.getenv("SLO_API_MS","250")+"ms","M","sys:","hold")