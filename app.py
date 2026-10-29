"""e-codices web app for Render, standalone single Python file."""

#!/usr/bin/env python3
"""Download an e-codices IIIF manuscript and make a facsimile PDF.

Pure Python 3 (no additional packages); image order and captions come from the
IIIF manifest, rather than an assumed numbered sequence. Files are cached.
"""
import argparse
import concurrent.futures
import json
import re
import struct
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit, unquote
from pathlib import Path

DEFAULT_URL = 'https://www.e-codices.unifr.ch/en/bbb/0258/119r/0/'


def manuscript_id(url):
    """Extract library and codex from e-codices URLs; ignore folio and anything after."""
    parsed = urlsplit(url.strip())
    parts = [unquote(p).lower() for p in parsed.path.split('/') if p]
    if parts and parts[0] in ('en', 'it', 'de', 'fr'):
        parts = parts[1:]
    if len(parts) == 1 and re.fullmatch(r'[a-z0-9]+-[a-z0-9]+', parts[0]):
        library, codex = parts[0].split('-', 1)
    elif len(parts) >= 2:
        library, codex = parts[:2]
    else:
        raise ValueError('URL e-codices non valido: mancano biblioteca e codice.')
    if not re.fullmatch(r'[a-z0-9]+', library) or not re.fullmatch(r'[a-z0-9]+', codex):
        raise ValueError('Sigla della biblioteca o numero del codice non validi.')
    return library, codex


def manifest_urls(library, codex):
    key = f'{library}-{codex}'
    return [f'https://{host}/metadata/iiif/{key}/manifest.json' for host in
            ('www.e-codices.ch', 'e-codices.ch', 'www.e-codices.unifr.ch', 'e-codices.unifr.ch')]


USER_AGENT = 'Mozilla/5.0 (compatible; IIIF-research-facsimile/1.0)'


def download(url, retries=3):
    err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': USER_AGENT,
                'Accept': 'image/jpeg,application/json,*/*',
                'Referer': 'https://www.e-codices.ch/'
            })
            with urllib.request.urlopen(req, timeout=65) as f:
                data = f.read()
            return data
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            err = exc
            if attempt + 1 < retries:
                time.sleep(1 + attempt * 2)
    raise RuntimeError(f'Errore di scaricamento da {url}: {err}')


def label_text(lab):
    if isinstance(lab, str):
        return lab
    if isinstance(lab, dict):
        for k in ('it', 'en', 'none', 'de', 'fr'):
            if lab.get(k):
                v = lab[k]
                return str(v[0] if isinstance(v, list) else v)
        return str(next(iter(lab.values()), 'pagina'))
    return str(lab)


def parse_manifest(doc):
    canvases = []
    if doc.get('sequences'):
        canvases = doc['sequences'][0].get('canvases', [])
    elif doc.get('items'):
        canvases = doc['items']
    else:
        raise ValueError('Manifesto IIIF senza sequenze o pagine.')
    pages = []
    for i, canvas in enumerate(canvases, 1):
        if canvas.get('images'):
            body = canvas['images'][0].get('resource', {})
        else:
            items = canvas.get('items', [])
            annotations = [a for p in items for a in p.get('items', [])]
            if not annotations:
                continue
            body = annotations[0].get('body', {})
        if isinstance(body, list):
            body = body[0]
        if not isinstance(body, dict):
            continue
        source = body.get('@id') or body.get('id') or ''
        svc = body.get('service', [])
        if isinstance(svc, dict):
            svc = [svc]
        service = next((v.get('@id') or v.get('id') for v in svc if isinstance(v, dict)), None)
        if not source and not service:
            continue
        name = label_text(canvas.get('label', f'Immagine {i}')).strip()
        pages.append({'label': name or f'Immagine {i}', 'source': source, 'service': service})
    if not pages:
        raise ValueError('Nessuna immagine individuata nel manifesto.')
    return pages


def image_urls(page, percent):
    candidates = []
    url = page.get('source', '')
    # e-codices historically publishes the IIIF Image API path in this form:
    # .../folio.jp2/full/full/0/default.jpg (or .../default/jpg)
    if url:
        for expression in ('/full/full/', '/full/max/'):
            if expression in url:
                candidates.append(url.replace(expression, f'/full/pct:{percent}/', 1))
    base = (page.get('service') or '').rstrip('/')
    if base:
        for suffix in (f'/full/pct:{percent}/0/default.jpg',
                       f'/full/pct:{percent}/0/default/jpg',
                       f'/full/pct:{percent}/0/native.jpg'):
            candidates.append(base + suffix)
    if url:
        candidates.append(url)
    return list(dict.fromkeys(candidates))


def jpeg_size(data):
    """Return W,H,channels from the JPEG SOF marker, without Pillow."""
    if not data.startswith(b'\xff\xd8'):
        raise ValueError('Il server non ha restituito un file JPEG.')
    pos = 2
    markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
               0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while pos < len(data)-4:
        if data[pos] != 255:
            pos += 1
            continue
        while pos < len(data) and data[pos] == 255:
            pos += 1
        if pos >= len(data):
            break
        marker = data[pos]; pos += 1
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        if marker == 0xDA:  # beginning of image data
            break
        if pos+2 > len(data):
            break
        size = int.from_bytes(data[pos:pos+2], 'big')
        if size < 2 or pos+size > len(data):
            break
        if marker in markers and size >= 8:
            h = int.from_bytes(data[pos+3:pos+5], 'big')
            w = int.from_bytes(data[pos+5:pos+7], 'big')
            channels = data[pos+7]
            if w > 0 and h > 0 and channels in (1, 3, 4):
                return w, h, channels
        pos += size
    raise ValueError('JPEG non riconosciuto o incompleto.')


def label_filename(s):
    s = re.sub(r'[^0-9A-Za-z._-]+', '_', s.strip())
    return s.strip('._')[:32] or 'pagina'


def get_image(page, dest, percent):
    if dest.is_file():
        try:
            with dest.open('rb') as f:
                jpeg_size(f.read(32768))
            return dest.stat().st_size
        except Exception:
            dest.unlink(missing_ok=True)
    errors = []
    for url in image_urls(page, percent):
        try:
            data = download(url, retries=2)
            jpeg_size(data[:65536])
            temp = dest.with_suffix('.tmp')
            temp.write_bytes(data)
            temp.replace(dest)
            return len(data)
        except Exception as e:
            errors.append(str(e))
    raise RuntimeError('; '.join(errors[-2:]))


def pdf_literal(s):
    # PDFDocEncoding handles common ASCII text and protects names from syntax.
    text = s.encode('ascii', errors='replace').decode('ascii')
    text = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    return f'({text})'.encode('ascii')


def create_pdf(pages, files, dest):
    """Embed JPEG bytes without recompression. Outline bookmarks = folio labels."""
    n = len(files)
    imageids = [5 + i*3 for i in range(n)]
    contentids = [6 + i*3 for i in range(n)]
    pageids = [7 + i*3 for i in range(n)]
    outlineids = [5 + 3*n + i for i in range(n)]
    infoid = 5 + 4*n
    total = infoid
    offsets = [0] * (total+1)

    def write_obj(fp, num, content):
        offsets[num] = fp.tell()
        fp.write(f'{num} 0 obj\n'.encode())
        fp.write(content)
        fp.write(b'\nendobj\n')

    def write_stream(fp, num, header, file):
        offsets[num] = fp.tell()
        fp.write(f'{num} 0 obj\n'.encode())
        fp.write(header)
        fp.write(b'\nstream\n')
        if isinstance(file, bytes):
            fp.write(file)
        else:
            with file.open('rb') as source:
                while True:
                    block = source.read(1024*1024)
                    if not block:
                        break
                    fp.write(block)
        fp.write(b'\nendstream\nendobj\n')

    temp = dest.with_suffix('.partial.pdf')
    with temp.open('wb') as f:
        f.write(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
        write_obj(f, 1, b'<< /Type /Catalog /Pages 2 0 R /Outlines 3 0 R /PageMode /UseOutlines /PageLabels 4 0 R >>')
        refs = b' '.join(f'{id} 0 R'.encode() for id in pageids)
        write_obj(f, 2, b'<< /Type /Pages /Count ' + str(n).encode() + b' /Kids [' + refs + b'] >>')
        write_obj(f, 3, f'<< /Type /Outlines /First {outlineids[0]} 0 R /Last {outlineids[-1]} 0 R /Count {n} >>'.encode())
        # Each page has its own folio label in compatible PDF viewers.
        labelobjs = [f'{i} << /P '.encode() + pdf_literal(pages[i]['label']) + b' >>' for i in range(n)]
        write_obj(f, 4, b'<< /Nums [ ' + b' '.join(labelobjs) + b' ] >>')
        for i, jpeg in enumerate(files):
            data = jpeg.read_bytes()[:65536]
            w,h,c = jpeg_size(data)
            color = {1: 'DeviceGray', 3: 'DeviceRGB', 4: 'DeviceCMYK'}[c]
            header = f'<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /{color} /BitsPerComponent 8 /Filter /DCTDecode /Length {jpeg.stat().st_size} >>'.encode()
            write_stream(f, imageids[i], header, jpeg)
            # Fit the full image on each page without cropping or decorative overlays.
            if h >= w:
                pw = 595.28
                ph = pw*h/w
            else:
                ph = 595.28
                pw = ph*w/h
            content = f'q {pw:.4f} 0 0 {ph:.4f} 0 0 cm /Im0 Do Q\n'.encode()
            write_stream(f, contentids[i], f'<< /Length {len(content)} >>'.encode(), content)
            pageobj = (f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {pw:.4f} {ph:.4f}] '
                       f'/Resources << /XObject << /Im0 {imageids[i]} 0 R >> >> '
                       f'/Contents {contentids[i]} 0 R >>').encode()
            write_obj(f, pageids[i], pageobj)
        for i, oid in enumerate(outlineids):
            prevstr = f'/Prev {outlineids[i-1]} 0 R ' if i else ''
            nextstr = f'/Next {outlineids[i+1]} 0 R ' if i < n-1 else ''
            title = pdf_literal(pages[i]['label'])
            ob = (b'<< /Title ' + title +
                  f' /Parent 3 0 R {prevstr}{nextstr}/Dest [{pageids[i]} 0 R /Fit] >>'.encode())
            write_obj(f, oid, ob)
        write_obj(f, infoid, b'<< /Title (Facsimile e-codices) /Creator (e-codices IIIF manifest) /Producer (ecodices_pdf.py) >>')
        xref = f.tell()
        f.write(f'xref\n0 {total+1}\n'.encode())
        f.write(b'0000000000 65535 f \n')
        for off in offsets[1:]:
            if off == 0:
                raise RuntimeError('Errore interno nella creazione del PDF.')
            f.write(f'{off:010d} 00000 n \n'.encode())
        f.write(f'trailer\n<< /Size {total+1} /Root 1 0 R /Info {infoid} 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    temp.replace(dest)


def main():
    ap = argparse.ArgumentParser(description='Scarica un manoscritto e-codices da URL e crea PDF.')
    ap.add_argument('url', nargs='?', default=DEFAULT_URL, help='Link e-codices al manoscritto, con o senza /2r/0/.')
    ap.add_argument('--manifest', help='Percorso di un manifesto IIIF scaricato manualmente (se il sito non risponde).')
    ap.add_argument('--percent', type=int, default=50, help='Percentuale della risoluzione originale (predefinita 50).')
    ap.add_argument('--workers', type=int, default=3, help='Scaricamenti simultanei (predefinito 3).')
    ap.add_argument('--folder', help='Cartella di destinazione (automatica se non indicata).')
    args = ap.parse_args()
    if not 1 <= args.percent <= 100:
        ap.error('--percent deve essere compreso tra 1 e 100.')
    if not 1 <= args.workers <= 5:
        ap.error('--workers deve essere compreso tra 1 e 5.')
    try:
        library, codex = manuscript_id(args.url)
    except ValueError as exc:
        ap.error(str(exc))
    key = f'{library}-{codex}'
    print(f'Manoscritto riconosciuto: {key} (ignoro foglio e segmenti successivi)')
    root = Path(args.folder or f'{key}_e-codices').resolve()
    root.mkdir(parents=True, exist_ok=True)
    saved_manifest = root / 'manifest.json'
    doc = None
    if args.manifest:
        doc = json.loads(Path(args.manifest).read_text(encoding='utf-8'))
    else:
        if saved_manifest.exists():
            try:
                doc = json.loads(saved_manifest.read_text(encoding='utf-8'))
                print('Uso il manifesto IIIF gia scaricato.')
            except Exception:
                pass
        if doc is None:
            for url in manifest_urls(library, codex):
                try:
                    print('Cerco il manifesto:', url, flush=True)
                    data = download(url, retries=1)
                    doc = json.loads(data)
                    parse_manifest(doc)
                    saved_manifest.write_bytes(data)
                    print('Manifesto acquisito.')
                    break
                except Exception as e:
                    print('  Non disponibile:', str(e)[:160], flush=True)
            if doc is None:
                print('\nNon riesco a raggiungere il manifesto IIIF. Il server potrebbe essere temporaneamente non disponibile.')
                print('Puoi riprovare in seguito: le immagini gia scaricate non verranno perse.')
                print('Se scarichi manualmente il manifesto, usa: python3 ecodices_pdf.py --manifest manifest.json')
                return 2
    pages = parse_manifest(doc)
    print(f'Trovate {len(pages)} immagini, nell\'ordine del manifesto IIIF.')
    images = root / f'immagini_{args.percent}pct'
    images.mkdir(exist_ok=True)
    files = [images / f'{i:04d}_{label_filename(p["label"])}.jpg' for i,p in enumerate(pages,1)]
    print(f'Qualita: {args.percent}% della risoluzione originale; download riavviabile.')
    # Detect an unreachable image server early rather than waiting for all pages.
    print('Verifico la prima immagine...', flush=True)
    try:
        get_image(pages[0], files[0], args.percent)
    except Exception as exc:
        print('Impossibile recuperare la prima immagine:', exc)
        return 3
    failed = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(get_image, page, dest, args.percent): i
                   for i,(page,dest) in enumerate(zip(pages,files),1) if i != 1}
        complete = 1
        for future in concurrent.futures.as_completed(futures):
            idx = futures[future]
            try:
                future.result()
            except Exception as exc:
                failed.append((idx, pages[idx-1]['label'], str(exc)))
                print(f'  ERRORE a {idx}/{len(pages)} ({pages[idx-1]["label"]})')
            complete += 1
            if complete % 10 == 0 or complete == len(pages):
                print(f'Immagini elaborate: {complete}/{len(pages)}', flush=True)
    if failed:
        report = root/'errori.txt'
        report.write_text('\n'.join(f'{i} {name}: {error}' for i,name,error in failed), encoding='utf-8')
        print(f'Immagini non disponibili: {len(failed)}. Dettagli in {report}')
        print('Il PDF non viene creato incompleto; ripeti il programma quando il server risponde.')
        return 4
    pdf = root/f'{key}.pdf'
    print('Creo il PDF completo, con segnalibri per le carte...', flush=True)
    create_pdf(pages, files, pdf)
    print(f'OPERAZIONE COMPLETATA: {pdf}')
    print(f'{len(files)} immagini, {pdf.stat().st_size/1024/1024:.1f} MB.')
    return 0



# Flask web interface
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
</style></head><body><main><h1>e-codices → PDF</h1><p>Scarica le immagini di un manoscritto tramite il manifesto IIIF e genera un PDF unico con segnalibri per le carte. La pagina del manoscritto può terminare anche con <code>/2r/0/</code>: il programma userà soltanto biblioteca e codice.</p><form id="f"><label for="url">URL del manoscritto</label><input required name="url" id="url" type="url" placeholder="https://www.e-codices.unifr.ch/en/bbb/0330/2r/0/"><label for="percent">Risoluzione delle immagini</label><select name="percent" id="percent"><option value="10">10% · Anteprima</option><option value="25">25% · Leggera</option><option value="50" selected>50% · Bilanciata</option><option value="75">75% · Alta qualità</option><option value="100">100% · Massima risoluzione disponibile</option></select><button id="start" type="submit">Crea PDF</button></form><div id="message" role="status" aria-live="polite"></div><progress id="progress" max="100" value="0" hidden></progress><div id="link"></div><p class="small">La durata dipende dal server e-codices. Su hosting Render gratuito, lavori molto grandi possono superare lo spazio temporaneo o essere interrotti da un riavvio. Le immagini non vengono ridimensionate una seconda volta durante la creazione del PDF. I file sono temporanei.</p></main><script>
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
        if percent not in (10,25,50,75,100): raise ValueError('Seleziona una risoluzione valida.')
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

