# Recuperado em 2026-11-23 do rascunho da sessão 4d6c23af (V9-P0). Lê api=/bearer= do ../.env; não contém segredos.
# É o script que acompanhou o caso farol/ondas (job_3294437207674cfe). plan_eval.py NÃO existia mais no rascunho: perdido.
import sys, time, re
sys.path.insert(0, "/home/lze/Documents/ClonField/clonfield-studio/tests/gpu")
import validate_remote as v
from pathlib import Path
env = v.read_env(v.DEFAULT_ENV)
c = v.Client(env["api"], env["bearer"]).connect()
run = v.Run(c, Path("/home/lze/Documents/ClonField/clonfield-studio/tests/gpu/out-agent"), 4500)
def mem():
    d = c.get("/system").json()
    return f"worker_ok={d['worker']['ok']} rss={d.get('worker_rss_gb')} GB livre={d['ram_free_gb']} GB"
print("MEM inicio", mem(), flush=True)
sid = c.post("/sessions", {}).json()["id"]
c.post(f"/sessions/{sid}/message", {"text": "crie uma imagem de um farol ao entardecer, depois amplie 2x e faça um vídeo curto dela com as ondas se movendo"}, timeout=600)
t0 = time.time()
while time.time() - t0 < 900:
    body = c.get(f"/sessions/{sid}").json()
    last = [m for m in body["messages"] if m["role"] == "assistant"][-1]
    if not last.get("pending"):
        break
    time.sleep(5)
tools = [t["tool"] for t in ((last.get("agent") or {}).get("trace") or [])]
jobs = [m.get("job") for m in body["messages"] if m.get("job")]
print("AGENTE", round(time.time() - t0), "s | ferramentas:", ", ".join(tools)[:200], "| jobs:", jobs, "| stop:", (last.get("agent") or {}).get("stop"), flush=True)
print("RESPOSTA", (last.get("text") or "")[:240].replace("\n", " "), flush=True)
if not jobs:
    print("SEM JOB", flush=True); sys.exit(0)
job, secs = run.wait(jobs[-1], "agente")
print("JOB", job["status"], round(secs), "s |", re.sub(r"\x1b\[[0-9;]*m", "", c.scrub(job.get("message") or ""))[-250:], flush=True)
print("MEM fim", mem(), flush=True)
if job["status"] == "concluído":
    print("FILES", run.collect("agent_job", job), flush=True)
sid2 = c.post("/sessions", {}).json()["id"]
c.post(f"/sessions/{sid2}/message", {"text": "oi, responda só com a palavra ok"}, timeout=600)
t1 = time.time()
while time.time() - t1 < 900:
    b2 = c.get(f"/sessions/{sid2}").json()
    l2 = [m for m in b2["messages"] if m["role"] == "assistant"][-1]
    if not l2.get("pending"):
        break
    time.sleep(5)
print("WAKE", round(time.time() - t1), "s |", (l2.get("text") or "")[:100].replace("\n", " "), flush=True)
print("FIM", mem(), flush=True)
