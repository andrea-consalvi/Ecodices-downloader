"""Unit tests: run after installing requirements with python -m unittest discover -s tests."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import app


class TestCore(unittest.TestCase):
    def test_manuscript_url(self):
        self.assertEqual(app.manuscript_id('https://www.e-codices.ch/en/doubleview/csg/0908/280b/'), 'csg-0908')
        self.assertEqual(app.manuscript_id('https://www.e-codices.ch/en/list/one/bbb/0258'), 'bbb-0258')
        self.assertEqual(app.manuscript_id('https://www.e-codices.unifr.ch/metadata/iiif/csg-0908/manifest.json'), 'csg-0908')
        with self.assertRaises(ValueError):
            app.manuscript_id('https://example.net/en/doubleview/csg/0908/280b')

    def test_secure_url(self):
        self.assertFalse(app.is_allowed_url('http://localhost:5000/private'))
        self.assertFalse(app.is_allowed_url('https://www.e-codices.ch.example.net/'))
        self.assertEqual(app.secure_url('http://www.e-codices.unifr.ch/loris/csg/example'),
                         'https://www.e-codices.unifr.ch/loris/csg/example')

    def test_images_v2(self):
        m = {'sequences': [{'canvases': [
            {'images': [{'resource': {'service': {'@id': 'http://www.e-codices.unifr.ch/loris/csg/one.jp2'}}}]},
            {'images': [{'resource': {'service': {'@id': 'http://www.e-codices.unifr.ch/loris/csg/two.jp2'}}}]}
        ]}]}
        urls = app.images_from_manifest(m)
        self.assertEqual(len(urls), 2)
        self.assertTrue(urls[0][1].startswith('https://'))
        self.assertIn('!2000,2000', app.image_candidates(urls[0], '2000')[0])

    def test_images_v3(self):
        m = {'items': [{'items': [{'items': [{'motivation': 'painting',
            'body': {'service': [{'id': 'https://www.e-codices.ch/loris/test.jp2'}]}}]}]}]}
        self.assertEqual(len(app.images_from_manifest(m)), 1)

    def test_http_app(self):
        c = app.app.test_client()
        self.assertEqual(c.get('/health').status_code, 200)
        self.assertIn(b'e-codices', c.get('/').data)
        self.assertEqual(c.post('/api/jobs', json={'url': 'http://localhost:9999'}).status_code, 400)

    def test_make_job_with_simulated_images(self):
        fixture = {'sequences': [{'canvases': [{'images': [{'resource': {'service':
            {'@id': 'https://www.e-codices.ch/loris/csg/test.jp2'}}}]}]}]}
        def download_image(index, image, quality, folder):
            path = folder / f'{index:05}.jpg'
            Image.new('RGB', (90, 120), 'white').save(path, 'JPEG')
            return path, path.stat().st_size
        job_id = 'synthetic-job'
        app.JOBS[job_id] = {'status': 'running', 'created_at': 0, 'percent': 0}
        with patch.object(app, 'fetch_manifest', return_value=fixture), patch.object(app, 'download_one', side_effect=download_image):
            app.run_job(job_id, 'csg-0908', '1200')
        try:
            self.assertEqual(app.JOBS[job_id]['status'], 'done')
            filename = Path(app.JOBS[job_id]['path'])
            self.assertTrue(filename.is_file())
            self.assertTrue(filename.read_bytes().startswith(b'%PDF'))
        finally:
            import shutil
            shutil.rmtree(Path(app.JOBS[job_id]['path']).parent, ignore_errors=True)
            app.JOBS.pop(job_id, None)

if __name__ == '__main__':
    unittest.main()
