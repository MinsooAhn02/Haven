# coding: utf-8
import subprocess
names=subprocess.check_output(['git','diff','--cached','--name-only','-z']).decode('utf-8').strip('\0').split('\0')
allowed={'README.md','기본프로젝트_계획.md','docs/구현명세/기본프로젝트_구현명세.md'}
assert names and all(n in allowed or n.startswith('docs/발표/') for n in names),names
assert not any(n.startswith('tasks/') or n.startswith('의견/') for n in names)
print('Staged scope verified:',len(names),'paths; no task logs or personal diagrams.')
