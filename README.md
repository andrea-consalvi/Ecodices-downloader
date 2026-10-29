# e-codices PDF Downloader

A browser-based interface that turns an e-codices manuscript URL into a single PDF, using the manuscript's IIIF manifest. It requires **no software** for people using the website.

## Publish online: no command line

1. Sign in to [GitHub](https://github.com/) and create a **new empty repository**, e.g. `ecodices-pdf` (public or private).
2. Open the empty repository and choose **Add file → Upload files**. From the extracted ZIP, upload `app.py`, `requirements.txt`, `render.yaml`, and the `templates` directory containing `index.html` (keep the directory structure). GitHub's web uploader supports dragging in the extracted project folder in modern browsers; double-check that `templates/index.html` appears in the repository. Click **Commit changes**.
3. Sign in to [Render](https://dashboard.render.com/) and select **New → Blueprint**. Connect your GitHub account and select the repository you just created.
4. Confirm the settings and select **Deploy Blueprint**. Render will install the dependencies and give you an HTTPS address ending in `.onrender.com`.
5. Share that address with users: they only need to paste a manuscript URL, choose a quality and click **Genera PDF**.

You can also use **New → Web Service** instead of Blueprint. Select the repository; Python runtime; build command `pip install -r requirements.txt`; start command `gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 app:app`.

**Important limits:** Render's free tier goes to sleep after inactivity, may restart during large downloads, has ephemeral local storage, and imposes bandwidth / CPU / memory restrictions. For reliable production downloads of very large manuscripts, use an appropriately sized paid instance. The PDF is retained for about one hour on the same running instance; it disappears after a restart. This initial version handles **one manuscript at a time per server** and has no user authentication. Do not expose it as an unrestricted mass-downloading service.

## Supported example

`https://www.e-codices.ch/en/doubleview/csg/0908/280b/`

which resolves to `csg-0908` and attempts the IIIF manifest at:

`https://www.e-codices.unifr.ch/metadata/iiif/csg-0908/manifest.json`

The browser URL identifies the *whole manuscript*, not only folio 280b.

## Performance

- Four parallel image downloads.
- JPEG bytes are embedded in the PDF without unnecessary recompression.
- PDF output streams to disk rather than being held in RAM.
- Image order follows the first IIIF sequence; supported Presentation API v2/v3.
- Safety limits: 1,100 images, 22 MB per image, 700 MB total source images.

## Local test for developers (optional)

`pip install -r requirements.txt && python app.py`

The website then runs at `http://127.0.0.1:5000`.

## Limitations

The app depends on e-codices responding successfully to IIIF manifest and image requests. It cannot bypass an outage, access restrictions, image licensing conditions, or the rate limits imposed by e-codices. Some manuscripts may use atypical IIIF responses. Avoid running many concurrent public downloads out of respect for the host library. This release includes automated tests with simulated IIIF data, but these tests and a live end-to-end e-codices download could **not** be executed in this environment because the dependencies and external server were unavailable.

## Automated local tests (developers only)

`python -m unittest discover -s tests`

Includes a simulated manuscript / PDF integration test; no real images are requested from the e-codices server in these tests.
