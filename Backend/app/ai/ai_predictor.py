"""
ai_predictor.py - Smart Water Meter (bagian AI)
Alur: foto -> YOLOv8-OBB (deteksi + sudut strip) -> luruskan (perspective warp) -> TrOCR -> validasi angka.

Folder model (hasil export notebook):
    trocr_final/
        best_obb.pt              detektor strip angka (YOLOv8-OBB)
        model/                   TrOCR (processor + model)
        config_inferensi.json    pengaturan inferensi

Pemakaian (Python):
    from ai_predictor import WaterMeterPredictor
    p = WaterMeterPredictor('trocr_final')
    hasil = p.predict('foto.jpg')            # path, bytes JPEG, atau array BGR (numpy)

Pemakaian (command line):
    python ai_predictor.py trocr_final foto1.jpg foto2.jpg

Pemakaian (API, butuh: pip install fastapi uvicorn python-multipart):
    MODEL_DIR=trocr_final uvicorn ai_predictor:app --host 0.0.0.0 --port 8000
    POST /predict  (form-data, field 'file' = gambar)
"""
import io, json, os, sys, time
from pathlib import Path

import cv2
import numpy as np

STATUS_VALID = 'valid'
STATUS_RESCAN = 'perlu_rescan'
STATUS_VERIFIKASI = 'perlu_verifikasi'


# ---------- util geometri & gambar (sama dengan yang diuji di notebook) ----------
def _order_pts(p):
    s = p.sum(1); d = np.diff(p, axis=1).ravel()
    return np.array([p[np.argmin(s)], p[np.argmin(d)], p[np.argmax(s)], p[np.argmax(d)]], dtype='float32')


def warp_poly(img, pts, margin=0.05):
    """Luruskan strip dari 4 titik OBB. Hasil selalu mendatar (lebar >= tinggi)."""
    pts = np.asarray(pts, dtype='float32'); c = pts.mean(0)
    box = _order_pts(c + (pts - c) * (1 + 2 * margin)); tl, tr, br, bl = box
    W = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    H = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    if W < 8 or H < 8:
        return None
    dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], dtype='float32')
    crop = cv2.warpPerspective(img, cv2.getPerspectiveTransform(box, dst), (W, H), borderMode=cv2.BORDER_REPLICATE)
    return cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE) if H > W else crop


def red_center_x(img):
    """Posisi horizontal (0..1) digit merah (liter). Dipakai untuk memilih arah 0/180 derajat."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m = ((hsv[..., 0] < 10) | (hsv[..., 0] > 170)) & (hsv[..., 1] > 90) & (hsv[..., 2] > 60)
    return None if m.sum() < 20 else float(np.where(m)[1].mean() / img.shape[1])


def blur_score(img):
    """Variansi Laplacian: makin kecil makin kabur."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def load_image(src):
    """path / bytes / array BGR -> array BGR (orientasi EXIF diterapkan)."""
    if isinstance(src, np.ndarray):
        return src
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(src)) if isinstance(src, (bytes, bytearray)) else Image.open(src)
    im = ImageOps.exif_transpose(im).convert('RGB')
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


def digits_to_m3(pred):
    """8 digit = 5 digit m3 (hitam) + 3 digit liter (merah). Mengembalikan m3 (float) atau None."""
    if isinstance(pred, str) and pred.isdigit() and len(pred) == 8:
        return int(pred[:5]) + int(pred[5:]) / 1000.0
    return None


# ---------- predictor ----------
class WaterMeterPredictor:
    def __init__(self, model_dir='trocr_final', device=None, model_version=None):
        import torch
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
        from ultralytics import YOLO

        self.torch = torch
        d = Path(model_dir)
        cfg = json.load(open(d / 'config_inferensi.json'))
        self.cfg = cfg
        self.dev = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        self.use_amp = self.dev == 'cuda'
        self.conf_roi = float(cfg.get('CONF_ROI', 0.25))
        self.margin = float(cfg.get('MARGIN', 0.05))
        self.ocr_thr = float(cfg.get('OCR_THR', 0.95))
        self.beams = int(cfg.get('NUM_BEAMS', 3))
        self.maxlen = int(cfg.get('MAXLEN', 12))
        # batas ketajaman: None = belum dikalibrasi (tidak dipakai). Isi di config_inferensi.json: "BLUR_MIN": <angka>
        self.blur_min = cfg.get('BLUR_MIN')
        self.model_version = model_version or cfg.get('MODEL_VERSION', 'v1')

        self.det = YOLO(str(d / cfg.get('DETECTOR', 'best_obb.pt')))
        self.proc = TrOCRProcessor.from_pretrained(d / 'model')
        self.tok = self.proc.tokenizer
        self.ocr = VisionEncoderDecoderModel.from_pretrained(d / 'model')
        for c in (self.ocr.config, self.ocr.generation_config):
            c.decoder_start_token_id = self.tok.cls_token_id
            c.pad_token_id = self.tok.pad_token_id
            c.eos_token_id = self.tok.eos_token_id
        self.ocr.config.vocab_size = self.ocr.config.decoder.vocab_size
        self.ocr.to(self.dev).eval()
        # no_repeat_ngram_size=0 wajib: bawaan checkpoint (3) merusak angka berulang seperti "000"
        self.gen = dict(max_new_tokens=self.maxlen, no_repeat_ngram_size=0, length_penalty=1.0)
        self.use_clahe = bool(cfg.get('USE_CLAHE', False))
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))

    # -- OCR --
    def _prep(self, bgr):
        from PIL import Image
        if self.use_clahe:
            l, a, b = cv2.split(cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB))
            bgr = cv2.cvtColor(cv2.merge([self._clahe.apply(l), a, b]), cv2.COLOR_LAB2BGR)
        return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))

    def _read(self, pv):
        torch = self.torch
        with torch.no_grad(), torch.autocast(self.dev, dtype=torch.float16, enabled=self.use_amp):
            out = self.ocr.generate(pv.to(self.dev), num_beams=self.beams, output_scores=True,
                                    return_dict_in_generate=True, early_stopping=True, **self.gen)
        texts = [t.replace(' ', '').strip() for t in self.tok.batch_decode(out.sequences, skip_special_tokens=True)]
        return texts, torch.exp(out.sequences_scores.float()).tolist()

    def _read_roi(self, crop):
        """Coba arah 0 dan 180 derajat; pilih yang menghasilkan 8 digit dengan confidence terbaik."""
        torch = self.torch
        cands = [crop, cv2.rotate(crop, cv2.ROTATE_180)]
        pv = torch.stack([self.proc.image_processor(self._prep(c), return_tensors='pt').pixel_values[0] for c in cands])
        texts, confs = self._read(pv)
        best = None
        for t, c, im in zip(texts, confs, cands):
            rc = red_center_x(im)
            key = (t.isdigit() and len(t) == 8, c + (0.05 if (rc is not None and rc > 0.5) else 0.0))
            if best is None or key > best[0]:
                best = (key, t, c)
        return best[1], float(best[2])

    # -- status --
    def decide_status(self, det_conf, pred, ocr_conf, blur=None):
        """valid | perlu_rescan | perlu_verifikasi.  (Aturan anomali penurunan / >50 m3 per 24 jam ada di backend.)"""
        if det_conf <= 0:
            return STATUS_RESCAN, 'strip angka tidak terdeteksi'
        if self.blur_min is not None and blur is not None and blur < self.blur_min:
            return STATUS_RESCAN, 'gambar terlalu kabur'
        if not (pred.isdigit() and len(pred) == 8):
            return STATUS_VERIFIKASI, 'hasil bukan 8 digit'
        if ocr_conf < self.ocr_thr:
            return STATUS_VERIFIKASI, 'confidence OCR rendah'
        return STATUS_VALID, 'ok'

    # -- API utama --
    def predict(self, src):
        """src: path | bytes | array BGR. Mengembalikan dict siap di-JSON-kan (field mengikuti Tabel 30 proposal)."""
        t0 = time.time()
        img = load_image(src)
        r = self.det(img, conf=self.conf_roi, verbose=False)[0]
        pred, ocr_conf, det_conf, box, blur = '', 0.0, 0.0, None, None
        if r.obb is not None and len(r.obb) > 0:
            i = int(r.obb.conf.argmax())
            pts = r.obb.xyxyxyxy[i].cpu().numpy()
            det_conf = float(r.obb.conf[i]); box = [[float(x), float(y)] for x, y in pts]
            crop = warp_poly(img, pts, self.margin)
            if crop is not None:
                blur = blur_score(crop)
                pred, ocr_conf = self._read_roi(crop)
        status, alasan = self.decide_status(det_conf, pred, ocr_conf, blur)
        return {
            'area_deteksi': box,                       # 4 titik [x, y] kotak berputar (piksel foto asli)
            'confidence_score': round(det_conf, 4),    # confidence deteksi ROI
            'hasil_ocr': pred,                         # string 8 digit (bisa tidak valid)
            'ocr_confidence': round(ocr_conf, 4),
            'nilai_pembacaan': digits_to_m3(pred),     # m3 (float) atau null
            'status_validasi': status,
            'alasan': alasan,
            'blur_score': None if blur is None else round(blur, 1),
            'model_version': self.model_version,
            'latency_ms': int((time.time() - t0) * 1000),
        }


# ---------- API opsional (FastAPI) ----------
def _make_app():
    from fastapi import FastAPI, File, UploadFile
    app = FastAPI(title='Smart Water Meter AI')
    state = {}

    @app.on_event('startup')
    def _load():
        state['p'] = WaterMeterPredictor(os.environ.get('MODEL_DIR', 'trocr_final'))

    @app.get('/health')
    def health():
        return {'ok': 'p' in state, 'model_version': state['p'].model_version if 'p' in state else None}

    @app.post('/predict')
    def predict(file: UploadFile = File(...)):
        # sengaja 'def' (bukan 'async def'): FastAPI menjalankannya di thread pool sehingga
        # inferensi yang berat tidak memblokir permintaan lain.
        return state['p'].predict(file.file.read())

    return app


try:
    app = _make_app()
except Exception:      # fastapi tidak terpasang: modul tetap bisa dipakai sebagai library
    app = None


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('pakai: python ai_predictor.py <folder_model> <foto1> [foto2 ...]'); sys.exit(1)
    p = WaterMeterPredictor(sys.argv[1])
    for f in sys.argv[2:]:
        print(f, json.dumps(p.predict(f), ensure_ascii=False))
