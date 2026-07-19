from __future__ import annotations

import ctypes
import json
import os
import re
import select
import shutil
import struct
import tempfile
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from r7a1a6c4_diag_common import MAX_BYTES, TARGETS, diff, fp, journal, normalized_json_hash, proc_snapshot, redact, run, sha, snap

_EVENT = struct.Struct('iIII')
_MASK = 0x8 | 0x4 | 0x80 | 0x100 | 0x200 | 0x400 | 0x800


class Watcher:
    def __init__(self, directory: Path):
        self.fd = -1; self.available = False
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            init, add = libc.inotify_init1, libc.inotify_add_watch
            init.argtypes=[ctypes.c_int]; init.restype=ctypes.c_int
            add.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_uint32]; add.restype=ctypes.c_int
            fd = init(os.O_NONBLOCK | os.O_CLOEXEC)
            if fd >= 0 and add(fd, os.fsencode(str(directory)), _MASK) >= 0:
                self.fd=fd; self.available=True
            elif fd >= 0: os.close(fd)
        except Exception:
            self.close()
    def close(self):
        if self.fd >= 0:
            try: os.close(self.fd)
            except OSError: pass
        self.fd=-1; self.available=False
    def read(self, timeout: float) -> list[dict[str,Any]]:
        if not self.available:
            time.sleep(timeout); return []
        ready,_,_=select.select([self.fd],[],[],timeout)
        if not ready: return []
        try: raw=os.read(self.fd,65536)
        except OSError: return []
        out=[]; off=0
        while off+_EVENT.size <= len(raw):
            wd,mask,cookie,length=_EVENT.unpack_from(raw,off); off+=_EVENT.size
            name=raw[off:off+length].split(b'\0',1)[0].decode('utf-8','replace'); off+=length
            out.append({'ts':time.time(),'wd':wd,'mask':int(mask),'cookie':int(cookie),'name':name})
        return out


def observe(seconds: int, poll_ms: int, needles: tuple[str,...]) -> dict[str,Any]:
    watcher=Watcher(TARGETS[0].parent); baseline=snap(TARGETS); events=[]; changes=[]
    deadline=time.monotonic()+max(1,seconds); interval=max(.02,poll_ms/1000)
    while time.monotonic()<deadline:
        events += watcher.read(interval)
        current=snap(TARGETS); delta=diff(baseline,current)
        if delta:
            epoch=time.time()
            changes.append({'detected_at':datetime.fromtimestamp(epoch,timezone.utc).isoformat(),'epoch':epoch,'changes':delta,'recent_inotify_events':events[-100:],'process_snapshot':proc_snapshot(needles),'journal':journal(epoch,needles)})
            baseline=current
            if len(changes)>=20: break
    available=watcher.available; watcher.close()
    return {'inotify_available':available,'inotify_event_count':len(events),'inotify_events':events[-500:],'change_event_count':len(changes),'change_events':changes,'final_fingerprints':{p:asdict(v) for p,v in snap(TARGETS).items()}}


def fetch_http() -> tuple[dict[str,Any],bytes]:
    attempts=(
        ('https_resolve',['curl','-kfsS','--max-time','12','--resolve','alimi.z-os.vip:443:127.0.0.1','https://alimi.z-os.vip/api/view_contract_latest.json']),
        ('http_host',['curl','-fsS','--max-time','12','-H','Host: alimi.z-os.vip','http://127.0.0.1/api/view_contract_latest.json']),
    )
    with tempfile.TemporaryDirectory(prefix='r7a1a6c4.http.') as tmp:
        body,headers=Path(tmp)/'body',Path(tmp)/'headers'
        for mode,base in attempts:
            p=run([*base[:-1],'-D',str(headers),'-o',str(body),'-w','%{http_code}',base[-1]],20)
            try: status=int(p.stdout.strip())
            except ValueError: status=0
            if p.returncode==0 and status and body.is_file():
                raw=body.read_bytes(); hdr=headers.read_text(errors='replace') if headers.is_file() else ''
                return {'mode':mode,'status':status,'size':len(raw),'sha256':sha(raw),'normalized_json_sha256':normalized_json_hash(raw),'headers':redact(hdr,5000)},raw
    return {'mode':'none','status':0,'size':0,'sha256':None,'normalized_json_sha256':None,'headers':''},b''


def find_origin(raw: bytes, roots: Iterable[Path]) -> dict[str,Any]:
    if not raw: return {'scanned_count':0,'exact_sha_matches':[],'normalized_json_matches':[]}
    expected_sha,expected_norm,expected_size=sha(raw),normalized_json_hash(raw),len(raw)
    exact=[]; normalized=[]; scanned=0
    for root in roots:
        candidates=root.rglob('*.json') if root.is_dir() else [root]
        try:
            for path in candidates:
                try:
                    if not path.is_file() or path.is_symlink() or path.stat().st_size>MAX_BYTES: continue
                    scanned+=1; data=None
                    if path.stat().st_size==expected_size:
                        data=path.read_bytes()
                        if sha(data)==expected_sha:
                            exact.append({'path':str(path),'size':len(data),'sha256':expected_sha}); continue
                    if expected_norm:
                        data=data if data is not None else path.read_bytes()
                        if normalized_json_hash(data)==expected_norm:
                            normalized.append({'path':str(path),'size':len(data),'sha256':sha(data)})
                except OSError: continue
        except OSError: continue
    return {'scanned_count':scanned,'exact_sha_matches':exact[:100],'normalized_json_matches':normalized[:100]}


def route_evidence(needles: tuple[str,...]) -> dict[str,Any]:
    records=[]
    def filtered(source:str,rc:int,text:str,rx:str):
        lines=[redact(x,1600) for x in text.splitlines() if any(n in x.lower() for n in needles) or re.search(rx,x,re.I)]
        records.append({'source':source,'rc':rc,'lines':lines[:600]})
    if shutil.which('caddy') and Path('/etc/caddy/Caddyfile').is_file():
        p=run(['caddy','adapt','--config','/etc/caddy/Caddyfile','--pretty'],30); filtered('caddy_adapt',p.returncode,p.stdout if p.returncode==0 else p.stderr,r'(alimi\.z-os\.vip|reverse_proxy|file_server|"root"|"handle")')
    p=run(['curl','-fsS','--max-time','5','http://127.0.0.1:2019/config/'],10)
    if p.returncode==0: filtered('caddy_admin',0,p.stdout,r'(alimi\.z-os\.vip|reverse_proxy|file_server|root|upstream)')
    if shutil.which('nginx'):
        p=run(['nginx','-T'],30); filtered('nginx_T',p.returncode,'\n'.join(x for x in (p.stdout,p.stderr) if x),r'(alimi\.z-os\.vip|proxy_pass|alias|root|location\s+/api)')
    return {'records':records}


def correlate(refs:list[dict[str,Any]],systemd:dict[str,Any],processes:list[dict[str,Any]],observation:dict[str,Any],historical:list[dict[str,Any]]) -> dict[str,Any]:
    by_path={}
    for hit in refs: by_path.setdefault(hit['path'],set()).update(hit['matched_terms'])
    proven=[]; strong=[]; static=[{'kind':'static_exact_reference','source_path':p,'matched_terms':sorted(m)} for p,m in by_path.items()]
    for proc in processes:
        if proc.get('relevant_fds'): proven.append({'kind':'process_open_fd',**proc})
        command=f"{proc.get('command','')} {proc.get('exe','')}".lower()
        for path,matches in by_path.items():
            if path.lower() in command or Path(path).name.lower() in command:
                strong.append({'kind':'active_process_source_reference','pid':proc.get('pid'),'unit':proc.get('unit'),'source_path':path,'matched_terms':sorted(matches),'command':proc.get('command')})
    unit_rows={str(x.get('Id')):x for x in systemd.get('units',[]) if x.get('Id')}
    for unit in systemd.get('units',[]):
        if unit.get('ActiveState')!='active': continue
        command=f"{unit.get('ExecStart','')} {unit.get('FragmentPath','')}".lower()
        for path,matches in by_path.items():
            if path.lower() in command or Path(path).name.lower() in command:
                strong.append({'kind':'active_unit_source_reference','unit':unit.get('Id'),'source_path':path,'matched_terms':sorted(matches),'exec_start':unit.get('ExecStart')})
    for event in observation.get('change_events',[]):
        for proc in event.get('process_snapshot',[]):
            if proc.get('relevant_fds'): proven.append({'kind':'event_correlated_open_fd','detected_at':event.get('detected_at'),**proc})
    for event in [*historical,*observation.get('change_events',[])]:
        for line in event.get('journal') or []:
            for name in re.findall(r'\b([A-Za-z0-9_.@-]+\.(?:service|timer))\b',line):
                unit=unit_rows.get(name,{}); command=f"{unit.get('ExecStart','')} {unit.get('FragmentPath','')}".lower(); matches=[]
                for path,terms in by_path.items():
                    if path.lower() in command or Path(path).name.lower() in command: matches.append({'source_path':path,'matched_terms':sorted(terms)})
                strong.append({'kind':'change_time_journal_unit','detected_at':event.get('detected_at'),'unit':name,'journal_line':line,'exec_start':unit.get('ExecStart',''),'source_matches':matches})
    def unique(rows):
        seen=set(); out=[]
        for row in rows:
            key=json.dumps(row,sort_keys=True,default=str)
            if key not in seen: seen.add(key); out.append(row)
        return out
    return {'proven':unique(proven),'strong':unique(strong),'static':unique(static)[:500]}
