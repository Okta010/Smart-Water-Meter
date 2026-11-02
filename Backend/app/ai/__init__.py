from pathlib import Path

_predictor = None

def get_predictor():
    """Satu instance untuk seluruh aplikasi; model dimuat saat pertama dipanggil."""
    global _predictor
    if _predictor is None:
        from .ai_predictor import WaterMeterPredictor
        _predictor = WaterMeterPredictor(Path(__file__).parent / 'trocr_final')
    return _predictor