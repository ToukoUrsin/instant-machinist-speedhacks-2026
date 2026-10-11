import concurrent.futures, json, pathlib, subprocess, time
repo=pathlib.Path.cwd(); out=repo/'swarm'/'runs'
items=[
'parser G41/G42 cutter compensation semantics','parser M98/M99 subprogram semantics','parser G68 rotation','parser G52/G54.1 offsets','parser inch metric switching','parser R arc edge cases','parser comments checksums','parser modal state','parser scientific notation','parser malformed input',
'stock finer cell accuracy','stock ball endmill','stock bull endmill','stock chamfer tool','stock spot drill','stock taper tool','stock boundary clipping','stock performance',
'checks holder collision','checks shank collision','checks rapid into stock','checks plunge','checks fixture collision','checks flute length','checks feeds speeds','checks chip load','checks false positives',
'cycle acceleration deceleration','cycle constant feed','cycle rapid timing','cycle corner blending','cycle metric units','run API compatibility','report JSON schema','CLI exit codes','fuzz property corpus','generated 2.5D fixtures','gouge ground truth','leftover ground truth','rapid collision ground truth','parser benchmark design','runtime benchmark design','precision recall benchmark','determinism','memory behavior','missing boundary tests','contract documentation','native compatibility','Fusion compatibility','fixture hygiene','highest impact improvement'
]
def one(i):
  aid=f'audit-{i+1:02d}'; d=out/aid; d.mkdir(parents=True,exist_ok=True); start=time.time()
  prompt=f'''You are read-only audit agent {aid} for Instant Machinist. Audit {items[i]} in the simulator under this repository. Do not edit files, use network, or open browsers. Return concise findings with file paths and 1-3 acceptance tests. This is saved as a run record.'''
  cmd=['timeout','150','codex','exec','--ephemeral','--json','--model','gpt-6.1-sol','--sandbox','read-only','--dangerously-bypass-hook-trust','-C',str(repo),prompt]
  p=subprocess.run(cmd,cwd=repo,text=True,capture_output=True)
  (d/'transcript.jsonl').write_text(p.stdout+'\n'+p.stderr)
  rec={'agent_id':aid,'item':items[i],'exit_code':p.returncode,'started_epoch':start,'ended_epoch':time.time(),'wall_s':round(time.time()-start,2),'transcript':'transcript.jsonl'}
  (d/'run.json').write_text(json.dumps(rec,indent=2)+'\n')
  return rec
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
  recs=list(ex.map(one,range(len(items))))
(out/'audit-manifest.json').write_text(json.dumps({'requested':len(items),'runs':recs},indent=2)+'\n')
print(json.dumps({'requested':len(items),'completed':len(recs),'ok':sum(r['exit_code']==0 for r in recs)},indent=2))
