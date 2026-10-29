"""Web front-end for the e-codices IIIF facsimile tool."""
from flask import Flask, request, jsonify, send_file, render_template_string, abort
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock, Thread
import json
import os
import shutil
import time
import uuid

from ecodices_pdf import manuscript_id, manifest_urls, download, parse_manifest, get_image, create_pdf, label_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024
ROOT = Path(os.environ.get('JOB_DIR', '/tmp/ecodices-jobs')).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
JOBS = {}
LOCK = Lock()
MAX_ACTIVE = 1   # prevent free Render instances from running out of RAM/disk
TTL_SECONDS = 2 * 3600

HTML = '''<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>e-codices · PDF manoscritti</title><style>
:root{font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#172033;background:#f5f7fb}*{box-sizing:border-box}main{max-width:780px;margin:5vh auto;padding:35px;background:white;border-radius:18px;box-shadow:0 8px 35px #10182812}h1{margin-top:0}p{line-height:1.55;color:#526075}label{font-weight:650;display:block;margin:22px 0 6px}input,select{width:100%;border:1px solid #b5beca;padding:13px;border-radius:8px;font-size:1rem}button,.dl{display:inline-block;background:#143d75;color:white;border:0;border-radius:9px;padding:14px 23px;cursor:pointer;margin-top:24px;font-weight:650;text-decoration:none}.dl{margin-top:10px}button:disabled{opacity:.5;cursor:default}.info{font-size:.88rem}#message{white-space:pre-wrap;padding:13px 0}progress{width:100%;height:20px}.small{font-size:.82rem;color:#64748b}code{overflow-wrap:anywhere}
</style></head><body><main><h1>e-codices → PDF</h1><p>Scarica le immagini di un manoscritto tramite il manifesto IIIF e genera un PDF unico con segnalibri per le carte. La pagina del manoscritto può terminare anche con <code>/2r/0/</code>: il programma userà soltanto biblioteca e codice.</p><form id="f"><label for="url">URL del manoscritto</label><input required name="url" id="url" type="url" placeholder="https://www.e-codices.unifr.ch/en/bbb/0330/2r/0/"><label for="percent">Risoluzione delle immagini</label><select name="percent" id="percent"><option value="25">25% · PDF più leggero</option><option value="50" selected>50% · Bilanciata</option><option value="100">100% · Massima risoluzione richiesta</option></select><button id="start" type="submit">Crea PDF</button></form><div id="message" role="status" aria-live="polite"></div><progress id="progress" max="100" value="0" hidden></progress><div id="link"></div><p class="small">La durata dipende dal server e-codices. Su hosting Render gratuito, lavori molto grandi possono superare lo spazio temporaneo o essere interrotti da un riavvio. Le immagini non vengono ridimensionate una seconda volta durante la creazione del PDF. I file sono temporanei.</p></main><script>
let timer;document.getElementById('f').addEventListener('submit',async e=>{e.preventDefault();clearTimeout(timer);let b=document.getElementById('start');b.disabled=true;document.getElementById('link').innerHTML='';document.getElementById('progress').hidden=false;const message=document.getElementById('message');try{let r=await fetch('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:document.getElementById('url').value,percent:parseInt(document.getElementById('percent').value)})});let j=await r.json();if(!r.ok)throw Error(j.error||'Errore');const id=j.id;async function poll(){try{let rr=await fetch('/api/jobs/'+id);let s=await rr.json();if(!rr.ok)throw Error(s.error||'Errore');message.textContent=s.message+'\n'+(s.total?`${s.done}/${s.total} immagini elaborate`:'');document.getElementById('progress').value=s.total?100*s.done/s.total:0;if(s.state==='done'){document.getElementById('link').innerHTML='<a class="dl" href="/api/jobs/'+id+'/pdf">Scarica il PDF completo</a>';b.disabled=false;return;}if(s.state==='error'){b.disabled=false;return;}timer=setTimeout(poll,2500)}catch(err){message.textContent=err.message;b.disabled=false}}poll()}catch(err){message.textContent=err.message;b.disabled=false}});
</script></body></html>'''


def cleanup():
    now = time.time()
    with LOCK:
        stale = [key for key, job in JOBS.items() if job['state'] in ('done', 'error') and now-job['updated'] > TTL_SECONDS]
        for key in stale:
            del JOBS[key]
    for key in stale:
        shutil.rmtree(ROOT / key, ignore_errors=True)


def set_job(key, **kw):
    with LOCK:
        if key in JOBS:
            JOBS[key].update(kw, updated=time.time())


def run_job(key, lib, codex, percent):
    folder = ROOT / key
    try:
        folder.mkdir(parents=True, exist_ok=True)
        set_job(key, message='Recupero il manifesto IIIF…')
        doc = None
        errors = []
        for u in manifest_urls(lib,codex):
            try:
                data = download(u, retries=1)
                doc = json.loads(data)
                pages = parse_manifest(doc)
                (folder/'manifest.json').write_bytes(data)
                break
            except Exception as exc:
                errors.append(str(exc)[:180])
        if doc is None:
            raise RuntimeError('Manifesto IIIF non raggiungibile. Il server e-codices potrebbe essere offline. '+('Ultimo errore: '+errors[-1] if errors else ''))
        n = len(pages)
        files_dir = folder/'images'; files_dir.mkdir(exist_ok=True)
        files = [files_dir/f'{i:04d}_{label_filename(p["label"])}.jpg' for i,p in enumerate(pages,1)]
        set_job(key,total=n, message='Verifico il server delle immagini…')
        get_image(pages[0],files[0],percent)
        set_job(key,done=1,message='Scaricamento delle immagini…')
        failures=[]
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures={pool.submit(get_image,p,d,percent):i for i,(p,d) in enumerate(zip(pages,files),1) if i>1}
            count=1
            for future in as_completed(futures):
                i=futures[future]
                try: future.result()
                except Exception as exc: failures.append((i,str(exc)[:150]))
                count += 1
                if count%3==0 or count==n: set_job(key,done=count)
        if failures:
            raise RuntimeError(f'{len(failures)} immagini non disponibili (es. carta {failures[0][0]}). Il PDF non viene creato incompleto. '+failures[0][1])
        set_job(key,done=n,message='Creo il PDF con segnalibri…')
        pdf=folder/f'{lib}-{codex}.pdf'
        create_pdf(pages,files,pdf)
        # Reclaim space after assembling, preserve PDF for later download.
        shutil.rmtree(files_dir,ignore_errors=True)
        set_job(key,state='done',message=f'PDF completato ({pdf.stat().st_size / (1024*1024):.1f} MB).',pdf=str(pdf))
    except Exception as exc:
        set_job(key,state='error',message='Errore: '+str(exc)[:600])
    finally:
        cleanup()


@app.get('/')
def index():
    return render_template_string(HTML)


@app.get('/health')
def health():
    return {'status':'ok'}


@app.post('/api/jobs')
def start():
    data=request.get_json(silent=True) or {}
    url=str(data.get('url','')).strip()
    try:
        if len(url)>1000 or not url.startswith(('https://','http://')):
            raise ValueError('Inserisci un URL completo di e-codices.')
        from urllib.parse import urlsplit
        host=(urlsplit(url).hostname or '').lower()
        if host not in ('www.e-codices.unifr.ch','e-codices.unifr.ch','www.e-codices.ch','e-codices.ch'):
            raise ValueError('È accettato soltanto un link e-codices.')
        lib,codex=manuscript_id(url)
        percent=int(data.get('percent',50))
        if percent not in (25,50,100): raise ValueError('Seleziona una risoluzione valida.')
    except (ValueError,TypeError) as exc:
        return jsonify(error=str(exc)),400
    cleanup()
    with LOCK:
        if sum(j['state']=='working' for j in JOBS.values())>=MAX_ACTIVE:
            return jsonify(error='Un PDF è già in preparazione. Riprova dopo il completamento.'),429
        key=uuid.uuid4().hex
        JOBS[key]={'state':'working','message':f'Manoscritto {lib}-{codex} riconosciuto; ignoro i segmenti successivi.','done':0,'total':0,'updated':time.time(),'pdf':None}
    Thread(target=run_job,args=(key,lib,codex,percent),daemon=True).start()
    return jsonify(id=key),202


@app.get('/api/jobs/<key>')
def status(key):
    with LOCK:
        j=JOBS.get(key)
        if not j: return jsonify(error='Lavoro non disponibile o scaduto.'),404
        return jsonify({k:v for k,v in j.items() if k in ('state','message','done','total')})


@app.get('/api/jobs/<key>/pdf')
def pdf_download(key):
    with LOCK:
        job=JOBS.get(key)
        p=job.get('pdf') if job and job['state']=='done' else None
    if not p or not Path(p).is_file(): abort(404)
    return send_file(p,as_attachment=True,download_name=Path(p).name,mimetype='application/pdf')


if __name__ == '__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))

