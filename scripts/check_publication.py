"""Check tracked/staged publication boundaries without printing secret values."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
FORBIDDEN_PREFIXES=('.compiler-work/','.venv/','private-media/','deliverables/','docs/evidence/','docs/screenshots/','staticfiles/','deploy/certs/')
FORBIDDEN_FILES={'.env','.local-secret','db.sqlite3','deploy/physical-target.json','deploy/sky130-user-design.json','deploy/fabric-postprocess-v1.json','deploy/fabric-postprocess-v1.zip'}
PATTERNS={
    'private key':re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'GitHub token':re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})\b'),
    'AWS access key':re.compile(rb'\bAKIA[A-Z0-9]{16}\b'),
    'JWT-shaped token':re.compile(rb'\beyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b'),
    'personal home path':re.compile(rb'(?:C:[/\\]Users[/\\]|/mnt/c/Users/)[A-Za-z][A-Za-z0-9._-]{2,}'),
}


def check(staged=False):
    files=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    findings=[];total=0;count=0
    for name in filter(None,files):
        count+=1
        if name in FORBIDDEN_FILES or name.startswith(FORBIDDEN_PREFIXES) or name.endswith(('.pem','.key','.pfx','.sqlite3')):
            findings.append({'file':name,'rule':'private/generated file'})
        data=subprocess.check_output(['git','show',':'+name],cwd=ROOT) if staged else (ROOT/name).read_bytes()
        total+=len(data)
        if len(data)>5*1024*1024:findings.append({'file':name,'rule':'file exceeds 5 MiB'})
        if name==Path(__file__).relative_to(ROOT).as_posix():continue
        for rule,pattern in PATTERNS.items():
            if pattern.search(data):findings.append({'file':name,'rule':rule})
    report={'files':count,'bytes':total,'findings':findings,'status':'failed' if findings else 'passed',
            'scope':'Publication boundary and known credential-pattern checks; no secret values emitted.'}
    print(json.dumps(report,indent=2))
    return bool(findings)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--staged',action='store_true')
    sys.exit(check(parser.parse_args().staged))
