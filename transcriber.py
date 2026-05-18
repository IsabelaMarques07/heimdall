import os
import torch
from faster_whisper import WhisperModel


def _detect_device():
    if torch.cuda.is_available():
        return "cuda", "float16"
    return "cpu", "int8"


class Transcriber:
    def __init__(self, model_name="base", language=None):
        device, compute_type = _detect_device()
        print(f"[whisper] Carregando modelo '{model_name}' em {device.upper()} ({compute_type})...")
        self.model = WhisperModel(model_name, device=device, compute_type=compute_type)
        self.language = language
        print("[whisper] Modelo pronto.\n")

    def transcribe(self, wav_path):
        """Transcreve o arquivo WAV e retorna o texto."""
        lang = self.language if self.language else None
        segments, _ = self.model.transcribe(wav_path, language=lang, beam_size=5)
        return " ".join(seg.text.strip() for seg in segments)

    def cleanup(self, wav_path):
        """Remove o arquivo WAV temporário."""
        try:
            os.unlink(wav_path)
        except OSError:
            pass
