                            if not chunk:
                                continue
                            received += len(chunk)
                            if received > MAX_IMAGE_BYTES:
                                raise RuntimeError('Immagine oltre il limite di 22 MB.')
                            stream.write(chunk)
                # Validate and preserve original JPEG data; conversion only for non-JPEG formats
                with Image.open(tmp) as im:
                    im.verify()
                with Image.open(tmp) as im:
                    if im.format == 'JPEG' and im.mode in ('RGB', 'L'):
                        target = folder / f'{index:05}.jpg'
                        tmp.replace(target)
                        return target, target.stat().st_size
                    target = folder / f'{index:05}.jpg'
                    ImageOps.exif_transpose(im).convert('RGB').save(target, 'JPEG', quality=88)
                tmp.unlink(missing_ok=True)
                return target, target.stat().st_size
            except (requests.RequestException, RuntimeError, OSError, UnidentifiedImageError, ValueError) as exc:
                tmp.unlink(missing_ok=True)
                last_error = exc
                if attempt == 0:
                    time.sleep(0.7)
    raise RuntimeError(f'Errore durante il download della pagina {index + 1}: {last_error}')


def update(job_id: str, **changes):
    with LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(changes)


def run_job(job_id: str, mid: str, quality: str):
    folder = None
    try:
        update(job_id, message='Lettura del manifest IIIF…')
        manifest = fetch_manifest(mid)
        images = images_from_manifest(manifest)
        folder = Path(tempfile.mkdtemp(prefix='ecodices_pdf_'))
        update(job_id, total=len(images), message=f'{len(images)} immagini individuate. Scaricamento avviato…')
        paths = [None] * len(images)
        total_bytes = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(download_one, i, item, quality, folder): i for i, item in enumerate(images)}
            for completed, future in enumerate(concurrent.futures.as_completed(futures), start=1):
                path, nbytes = future.result()
                paths[futures[future]] = path
                total_bytes += nbytes
                if total_bytes > MAX_TOTAL_BYTES:
                    for pending in futures:
                        pending.cancel()
                    raise RuntimeError('Limite di spazio raggiunto (700 MB). Prova la qualità Veloce.')
                update(job_id, percent=int(completed / len(images) * 92),
                       message=f'Immagini scaricate: {completed}/{len(images)}')
        update(job_id, percent=94, message='Assemblaggio del PDF senza ricompressione…')
        output_path = folder / f'{mid}.pdf'
        # Important: outputstream avoids allocating the whole PDF in memory
        with output_path.open('wb') as output:
            img2pdf.convert([str(p) for p in paths], outputstream=output)
        for image_path in paths:
            image_path.unlink(missing_ok=True)
        update(job_id, status='done', percent=100,
               message=f'PDF pronto: {len(paths)} immagini, {output_path.stat().st_size / (1024 ** 2):.1f} MB.',
               path=str(output_path), filename=output_path.name)
    except Exception as exc:
        update(job_id, status='error', message=str(exc), percent=0)
        if folder:
            shutil.rmtree(folder, ignore_errors=True)


def cleanup():
    now = time.time()
    with LOCK:
        expired = [job_id for job_id, job in JOBS.items()
                   if job['status'] != 'running' and now - job['created_at'] > MAX_AGE_SECONDS]
        deleted = [JOBS.pop(job_id) for job_id in expired]
    for job in deleted:
        if job.get('path'):
            shutil.rmtree(Path(job['path']).parent, ignore_errors=True)


@app.get('/')
def index():
    return render_template('index.html', example=DEFAULT_URL)


@app.get('/health')
def health():
    return jsonify(status='ok')


@app.post('/api/jobs')
def create_job():
    cleanup()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='Richiesta non valida.'), 400
    try:
        mid = manuscript_id(str(data.get('url', '')).strip())
        quality = str(data.get('quality', '2000'))
        if quality not in ('1200', '2000', '3000', 'full'):
            raise ValueError('Risoluzione non valida.')
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    with LOCK:
        if sum(j['status'] == 'running' for j in JOBS.values()) >= MAX_DOWNLOADS:
            return jsonify(error='È già in corso un download. Riprova quando sarà terminato.'), 429
        job_id = uuid.uuid4().hex
        JOBS[job_id] = {'status': 'running', 'message': 'Preparazione…', 'percent': 0,
                        'created_at': time.time(), 'total': 0}
    threading.Thread(target=run_job, args=(job_id, mid, quality), daemon=True).start()
    return jsonify(id=job_id), 202


@app.get('/api/jobs/<job_id>')
def status(job_id):
    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify(error='Operazione non trovata o scaduta.'), 404
        return jsonify({key: value for key, value in job.items()
                        if key not in ('path', 'filename', 'created_at')})


@app.get('/api/jobs/<job_id>/download')
def download(job_id):
    with LOCK:
        job = JOBS.get(job_id)
