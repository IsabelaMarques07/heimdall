import os
import sys
import queue
import signal
import argparse
from datetime import datetime

from audio_capture import AudioCapture
from transcriber import Transcriber


def get_output_path():
    os.makedirs("transcricoes", exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return os.path.join("transcricoes", f"transcricao_{timestamp}.txt")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Heimdall - Transcritor de áudio do sistema"
    )
    parser.add_argument(
        "--model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Modelo Whisper a usar (default: base). Modelos maiores = mais lento, mais preciso.",
    )
    parser.add_argument(
        "--lang",
        default=None,
        metavar="LANG",
        help="Idioma do áudio (ex: pt, en). Omitir = detecção automática.",
    )
    parser.add_argument(
        "--chunk",
        default=30,
        type=int,
        metavar="SEGUNDOS",
        help="Duração de cada trecho capturado antes de transcrever (default: 30).",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    output_path = get_output_path()
    print(f"Arquivo de saída: {output_path}")
    print(f"Modelo: {args.model} | Idioma: {args.lang or 'auto'} | Chunk: {args.chunk}s")
    print("Pressione Ctrl+C para parar.\n")

    transcriber = Transcriber(model_name=args.model, language=args.lang)
    capture = AudioCapture(chunk_duration=args.chunk)

    running = True

    def handle_stop(sig, frame):
        nonlocal running
        print("\n[main] Parando captura...")
        running = False
        capture.stop()

    signal.signal(signal.SIGINT, handle_stop)

    capture.start()

    with open(output_path, "a", encoding="utf-8") as f:
        header = f"=== Transcrição iniciada em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n\n"
        f.write(header)

        while running or not capture.audio_queue.empty():
            try:
                wav_path = capture.audio_queue.get(timeout=1)
            except queue.Empty:
                continue

            if wav_path is None:
                # erro na captura de áudio
                print("[main] Captura encerrada por erro.")
                break

            print(f"[whisper] Transcrevendo chunk...", end=" ", flush=True)
            text = transcriber.transcribe(wav_path)
            transcriber.cleanup(wav_path)

            if text:
                timestamp = datetime.now().strftime("%H:%M:%S")
                line = f"[{timestamp}] {text}\n"
                print(line, end="")
                f.write(line)
                f.flush()
            else:
                print("(silêncio)")

        f.write(f"\n=== Transcrição encerrada em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")

    print(f"\nTranscrição salva em: {output_path}")


if __name__ == "__main__":
    main()
