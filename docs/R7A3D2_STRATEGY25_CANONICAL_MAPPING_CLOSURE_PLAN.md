# R7.A3D2 Strategy25 Canonical Mapping Closure Plan

A3D에서 발생한 25개 CONFLICT를 자동 승인하지 않고 후보를 경로·callable 기준으로 중복 제거한다.

우선순위는 direct strategy module, Git에 존재하는 target path, explicit registry callable, shared engine plus strategy config 순이다. 진단·감사·smoke·display 도구의 단순 문자열 언급은 감점한다.

자동 축소는 최소 점수와 runner-up 대비 margin을 동시에 만족해야 한다. 기준 미달은 `EXPLICIT_MAPPING_REQUIRED`로 남기며 mapping·전략·runtime을 수정하지 않는다.
