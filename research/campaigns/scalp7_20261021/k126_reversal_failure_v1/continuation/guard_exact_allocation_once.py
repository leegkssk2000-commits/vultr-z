"""Resume only the pre-economic capacity read after exact live-lease diagnosis.
No old queued run is cancelled/ignored by age: use GitHub's actual group membership.
No strategy/data/cost/freeze changes. Preserve first guard error and no blind replay.
"""
from pathlib import Path
from datetime import datetime,timezone
import json,time,urllib.request,urllib.error
import guard_existing_slot as original
S=Path(__file__).resolve().parent

def live_request(path, allow_absent_group=False):
    if original.REQUESTS>=35:raise RuntimeError('PUBLIC_REQUEST_BUDGET_REACHED')
    original.REQUESTS+=1
    req=urllib.request.Request(original.API+path,headers={'User-Agent':'zel-existing-owner-live-lease-recovery','Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2026-03-10'})
    try:
        with urllib.request.urlopen(req,timeout=20) as response:
            if 'rel="next"' in (response.headers.get('Link') or ''):raise RuntimeError('LIVE_ALLOCATION_PAGINATION_REQUIRED')
            return json.load(response)
    except urllib.error.HTTPError as e:
        if e.code==404 and allow_absent_group:return {'_group_inactive_404':True}
        if e.code in (403,429):
            original.emit('HTTP_LIMIT_OR_PERMISSION_HOLD_NO_BYPASS',http_status=e.code,remaining=e.headers.get('X-RateLimit-Remaining'),reset=e.headers.get('X-RateLimit-Reset'),economic_started=(S/'STARTED.json').exists())
        raise

def live_capacity():
    # Both workload classes have actual verified economic replay steps. The
    # legacy Strategy25 job uses a different group; do not add a third replay.
    relevant={original.GROUP,'a1-strategy25-improvement-league-refs/heads/master'}
    listing=live_request('/actions/concurrency_groups?per_page=100')
    groups=listing.get('concurrency_groups')
    if not isinstance(groups,list) or int(listing.get('total_count',-1))!=len(groups):raise RuntimeError('GROUP_LIST_INCOMPLETE')
    busy=[];evidence=[{'active_group_listing':listing,'captured_at_utc':original.now()}]
    import urllib.parse
    for group in groups:
        name=group.get('group_name','')
        if name not in relevant:continue
        data=live_request('/actions/concurrency_groups/'+urllib.parse.quote(name,safe=''),allow_absent_group=True)
        if data.get('_group_inactive_404'):raise RuntimeError('GROUP_COMPLETED_DURING_PREFLIGHT_RECHECK_REQUIRED')
        members=data.get('group_members')
        if data.get('group_name','').casefold()!=name.casefold() or not isinstance(members,list) or int(data.get('total_count',-1))!=len(members):raise RuntimeError('LIVE_GROUP_RESPONSE_INCOMPLETE')
        evidence.append({'live_group':data,'captured_at_utc':original.now()})
        busy.extend({'id':m['run_id'],'name':m.get('run_name'),'status':m['status'],'job_id':m.get('job_id'),'basis':'EXACT_LIVE_ECONOMIC_GROUP_MEMBER','group':name} for m in members if m['status']!='completed')
    return busy,evidence

if __name__=='__main__':
    original.request=live_request
    original.capacity=live_capacity
    try:original.main()
    except Exception as e:
        original.emit('CAPACITY_RECOVERY_HOLD_NO_BLIND_RETRY',error_type=type(e).__name__,error=str(e),economic_started=(S/'STARTED.json').exists())
        raise
