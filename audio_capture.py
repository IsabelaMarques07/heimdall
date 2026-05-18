import wave
import tempfile
import threading
import queue
import os

import pyaudiowpatch as pyaudio

CHUNK = 512
FORMAT = pyaudio.paInt16


def find_loopback_device(p):
    """Encontra o dispositivo loopback WASAPI do speaker padrão."""
    try:
        wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    except OSError:
        raise RuntimeError("WASAPI não disponível. Certifique-se de estar no Windows.")

    default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])

    if default_speakers.get("isLoopbackDevice", False):
        return default_speakers

    for loopback in p.get_loopback_device_info_generator():
        if default_speakers["name"] in loopback["name"]:
            return loopback

    raise RuntimeError(
        f"Dispositivo loopback não encontrado para: {default_speakers['name']}\n"
        "Verifique se o driver de áudio suporta loopback."
    )


class AudioCapture:
    def __init__(self, chunk_duration=30):
        self.chunk_duration = chunk_duration
        self.audio_queue = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = None
        self.device_name = None

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _capture_loop(self):
        p = pyaudio.PyAudio()
        try:
            device_info = find_loopback_device(p)
            self.device_name = device_info["name"]
            channels = device_info["maxInputChannels"]
            rate = int(device_info["defaultSampleRate"])
            sample_size = p.get_sample_size(FORMAT)

            stream = p.open(
                format=FORMAT,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=device_info["index"],
                frames_per_buffer=CHUNK,
            )

            print(f"[audio] Capturando de: {device_info['name']}")

            while not self._stop_event.is_set():
                frames = []
                num_chunks = int(rate / CHUNK * self.chunk_duration)

                for _ in range(num_chunks):
                    if self._stop_event.is_set():
                        break
                    data = stream.read(CHUNK, exception_on_overflow=False)
                    frames.append(data)

                if frames:
                    wav_path = _save_wav(frames, channels, sample_size, rate)
                    self.audio_queue.put(wav_path)

            stream.stop_stream()
            stream.close()
        except Exception as e:
            print(f"[audio] Erro na captura: {e}")
            self.audio_queue.put(None)  # sinaliza erro para o loop principal
        finally:
            p.terminate()


def _save_wav(frames, channels, sample_size, rate):
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    with wave.open(tmp.name, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_size)
        wf.setframerate(rate)
        wf.writeframes(b"".join(frames))
    return tmp.name
