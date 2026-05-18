import os
import queue
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from audio_capture import AudioCapture
from transcriber import Transcriber
from formatter import format_transcription

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

OUTPUT_DIR = "transcricoes"

# Cores auxiliares
_GRAY = ("gray50", "gray60")
_ORANGE = "#e5a000"


class HeimdallApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Heimdall")
        self.minsize(700, 500)
        self.geometry("860x600")

        self._capture = None
        self._worker_thread = None
        self._running = False
        self._output_file = None
        self._output_path = None
        self._config_widgets: list = []

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        # --- Config ---
        cfg = ctk.CTkFrame(self, fg_color="transparent")
        cfg.pack(fill="x", padx=16, pady=(16, 0))

        ctk.CTkLabel(cfg, text="Modelo:").pack(side="left")
        self._model_var = tk.StringVar(value="base")
        model_cb = ctk.CTkComboBox(
            cfg,
            variable=self._model_var,
            values=["tiny", "base", "small", "medium", "large"],
            width=110,
        )
        model_cb.pack(side="left", padx=(6, 20))
        self._config_widgets.append(model_cb)

        ctk.CTkLabel(cfg, text="Idioma:").pack(side="left")
        self._lang_var = tk.StringVar(value="")
        lang_entry = ctk.CTkEntry(cfg, textvariable=self._lang_var, width=64, placeholder_text="auto")
        lang_entry.pack(side="left", padx=(6, 4))
        ctk.CTkLabel(cfg, text="pt / en / auto", text_color=_GRAY).pack(side="left", padx=(0, 20))
        self._config_widgets.append(lang_entry)

        ctk.CTkLabel(cfg, text="Chunk:").pack(side="left")
        self._chunk_var = tk.StringVar(value="30")
        chunk_entry = ctk.CTkEntry(cfg, textvariable=self._chunk_var, width=52)
        chunk_entry.pack(side="left", padx=(6, 4))
        ctk.CTkLabel(cfg, text="s", text_color=_GRAY).pack(side="left")
        self._config_widgets.append(chunk_entry)

        # --- Controle ---
        ctrl = ctk.CTkFrame(self, fg_color="transparent")
        ctrl.pack(fill="x", padx=16, pady=(10, 0))

        self._btn = ctk.CTkButton(ctrl, text="Iniciar", command=self._toggle, width=100)
        self._btn.pack(side="left")

        self._status_var = tk.StringVar(value="Pronto.")
        self._status_lbl = ctk.CTkLabel(ctrl, textvariable=self._status_var, text_color=_GRAY)
        self._status_lbl.pack(side="left", padx=14)

        self._lag_var = tk.StringVar(value="")
        ctk.CTkLabel(ctrl, textvariable=self._lag_var, text_color=_ORANGE).pack(side="right", padx=8)

        # Divisor
        ctk.CTkFrame(self, height=1, fg_color=("gray75", "gray30")).pack(fill="x", padx=16, pady=(12, 0))

        # --- Área de texto ---
        self._text = ctk.CTkTextbox(self, wrap="word", font=("Consolas", 10))
        self._text.pack(fill="both", expand=True, padx=16, pady=(10, 0))
        self._text.configure(state="disabled")

        # --- Rodapé ---
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=16, pady=(10, 14))

        self._filepath_var = tk.StringVar(value="")
        ctk.CTkLabel(footer, textvariable=self._filepath_var, text_color=_GRAY, anchor="w").pack(side="left")

        ctk.CTkButton(footer, text="Copiar tudo", command=self._copy_all, width=110).pack(side="right")
        ctk.CTkButton(footer, text="Limpar", command=self._clear_text, width=80, fg_color="transparent",
                      border_width=1).pack(side="right", padx=(0, 8))
        ctk.CTkButton(footer, text="Formatar .txt → .md", command=self._open_formatter, width=160,
                      fg_color="transparent", border_width=1).pack(side="right", padx=(0, 8))

    # ------------------------------------------------------------------
    # Controle start/stop
    # ------------------------------------------------------------------

    def _toggle(self):
        if self._running:
            self._stop()
        else:
            self._start()

    def _start(self):
        model = self._model_var.get()
        lang = self._lang_var.get().strip() or None
        try:
            chunk = int(self._chunk_var.get())
        except ValueError:
            chunk = 30

        self._btn.configure(text="Parar")
        self._set_config_state("disabled")
        self._set_status("Carregando modelo...")
        self._running = True

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._output_path = os.path.join(OUTPUT_DIR, f"transcricao_{ts}.txt")
        self._filepath_var.set(self._output_path)
        self._output_file = open(self._output_path, "a", encoding="utf-8")
        self._output_file.write(
            f"=== Iniciado em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n\n"
        )

        self._worker_thread = threading.Thread(
            target=self._worker, args=(model, lang, chunk), daemon=True
        )
        self._worker_thread.start()

    def _stop(self):
        self._running = False
        self._btn.configure(state="disabled", text="Parando...")
        self._set_status("Parando...")
        if self._capture:
            self._capture.stop()

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _worker(self, model, lang, chunk):
        try:
            transcriber = Transcriber(model_name=model, language=lang)
            self._safe(lambda: self._set_status("Capturando..."))

            capture = AudioCapture(chunk_duration=chunk)
            self._capture = capture
            capture.start()

            while self._running or not capture.audio_queue.empty():
                try:
                    wav_path = capture.audio_queue.get(timeout=1)
                except queue.Empty:
                    continue

                if wav_path is None:
                    self._safe(lambda: self._set_status("Erro na captura de audio."))
                    break

                pending = capture.audio_queue.qsize()
                if pending > 0:
                    self._safe(lambda n=pending: self._lag_var.set(f"fila: {n} chunk(s) pendente(s)"))
                else:
                    self._safe(lambda: self._lag_var.set(""))

                self._safe(lambda: self._set_status("Transcrevendo..."))
                text = transcriber.transcribe(wav_path)
                transcriber.cleanup(wav_path)

                if text:
                    ts = datetime.now().strftime("%H:%M:%S")
                    line = f"[{ts}] {text}\n"
                    self._safe(lambda l=line: self._append(l))
                    self._output_file.write(line)
                    self._output_file.flush()
                else:
                    self._safe(lambda: self._append("[silêncio]\n", muted=True))

                if self._running:
                    self._safe(lambda: self._set_status("Capturando..."))

        except Exception as e:
            self._safe(lambda err=e: self._set_status(f"Erro: {err}"))
        finally:
            self._finalize()

    def _finalize(self):
        if self._output_file:
            self._output_file.write(
                f"\n=== Encerrado em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n"
            )
            self._output_file.close()
            self._output_file = None

        def reset():
            self._btn.configure(state="normal", text="Iniciar")
            self._set_config_state("normal")
            self._set_status(f"Salvo em: {self._output_path}")
            self._lag_var.set("")
            self._running = False

        self._safe(reset)

    # ------------------------------------------------------------------
    # Helpers de UI
    # ------------------------------------------------------------------

    def _safe(self, fn):
        self.after(0, fn)

    def _set_status(self, msg):
        self._status_var.set(msg)

    def _append(self, text, muted=False):
        self._text.configure(state="normal")
        if muted:
            self._text.insert("end", text, "muted")
            self._text.tag_config("muted", foreground="gray50")
        else:
            self._text.insert("end", text)
        self._text.see("end")
        self._text.configure(state="disabled")

    def _clear_text(self):
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")

    def _copy_all(self):
        content = self._text.get("1.0", "end").strip()
        if content:
            self.clipboard_clear()
            self.clipboard_append(content)
            self._set_status("Copiado para a area de transferencia.")

    def _set_config_state(self, state):
        for w in self._config_widgets:
            w.configure(state=state)

    def _open_formatter(self):
        FormatWindow(self)

    def _on_close(self):
        if self._running:
            self._stop()
        self.after(300, self.destroy)


# ======================================================================

class FormatWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Formatar transcrição")
        self.resizable(True, True)
        self.minsize(560, 420)
        self.grab_set()

        self._files: list[str] = []
        self._model_var = tk.StringVar(value="llama3.2")
        self._status = tk.StringVar(value="Adicione arquivos .txt para formatar.")

        self._build_ui()
        self.geometry("640x580")

    def _build_ui(self):
        # --- Lista de arquivos ---
        ctk.CTkLabel(self, text="Arquivos  (ordem cronológica pelo nome)", anchor="w").pack(
            fill="x", padx=16, pady=(16, 4)
        )

        list_row = ctk.CTkFrame(self, fg_color="transparent")
        list_row.pack(fill="x", padx=16)

        # Listbox estilizado manualmente para combinar com o tema dark
        lb_frame = ctk.CTkFrame(list_row, corner_radius=6)
        lb_frame.pack(side="left", fill="both", expand=True)

        self._listbox = tk.Listbox(
            lb_frame,
            selectmode=tk.SINGLE,
            height=5,
            bg="#2b2b2b",
            fg="#dce4ee",
            selectbackground="#1f6aa5",
            selectforeground="#ffffff",
            activestyle="none",
            borderwidth=0,
            highlightthickness=0,
            font=("Segoe UI", 10),
        )
        self._listbox.pack(side="left", fill="both", expand=True, padx=4, pady=4)

        sb = tk.Scrollbar(lb_frame, orient="vertical", command=self._listbox.yview,
                          bg="#2b2b2b", troughcolor="#2b2b2b", borderwidth=0)
        sb.pack(side="left", fill="y", pady=4)
        self._listbox.config(yscrollcommand=sb.set)

        btn_col = ctk.CTkFrame(list_row, fg_color="transparent")
        btn_col.pack(side="left", fill="y", padx=(10, 0))
        ctk.CTkButton(btn_col, text="Adicionar", command=self._browse, width=100).pack(pady=(0, 6))
        ctk.CTkButton(btn_col, text="Remover", command=self._remove_selected, width=100,
                      fg_color="transparent", border_width=1).pack(pady=(0, 6))
        ctk.CTkButton(btn_col, text="Limpar", command=self._clear_list, width=100,
                      fg_color="transparent", border_width=1).pack()

        # --- Modelo ---
        model_row = ctk.CTkFrame(self, fg_color="transparent")
        model_row.pack(fill="x", padx=16, pady=(12, 0))

        ctk.CTkLabel(model_row, text="Modelo:").pack(side="left")
        ctk.CTkComboBox(
            model_row,
            variable=self._model_var,
            values=["llama3.2", "llama3.2:1b", "qwen2.5", "qwen2.5:3b", "mistral", "phi3"],
            width=150,
        ).pack(side="left", padx=(8, 10))
        ctk.CTkLabel(model_row, text="(modelo instalado no Ollama)", text_color=_GRAY).pack(side="left")

        # Divisor
        ctk.CTkFrame(self, height=1, fg_color=("gray75", "gray30")).pack(fill="x", padx=16, pady=(12, 0))

        # --- Preview streaming ---
        ctk.CTkLabel(self, text="Preview:", anchor="w").pack(fill="x", padx=16, pady=(8, 4))
        self._preview = ctk.CTkTextbox(self, wrap="word", font=("Consolas", 9))
        self._preview.pack(fill="both", expand=True, padx=16)
        self._preview.configure(state="disabled")

        # --- Status + progress ---
        self._status_lbl = ctk.CTkLabel(self, textvariable=self._status, text_color=_GRAY,
                                        anchor="w", wraplength=580)
        self._status_lbl.pack(fill="x", padx=16, pady=(6, 2))

        self._progress = ctk.CTkProgressBar(self, mode="indeterminate")
        self._progress.pack(fill="x", padx=16, pady=(0, 0))
        self._progress.set(0)

        # --- Botões ---
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(10, 14))

        self._btn = ctk.CTkButton(btn_row, text="Formatar", command=self._start, width=110)
        self._btn.pack(side="left")
        ctk.CTkButton(btn_row, text="Fechar", command=self.destroy, width=90,
                      fg_color="transparent", border_width=1).pack(side="right")

    # ------------------------------------------------------------------

    def _browse(self):
        initial = os.path.abspath("transcricoes") if os.path.isdir("transcricoes") else "."
        paths = filedialog.askopenfilenames(
            parent=self,
            title="Selecionar transcrições",
            initialdir=initial,
            filetypes=[("Arquivos de texto", "*.txt"), ("Todos", "*.*")],
        )
        for path in paths:
            if path not in self._files:
                self._files.append(path)
        self._refresh_list()

    def _remove_selected(self):
        sel = self._listbox.curselection()
        if sel:
            self._files.pop(sel[0])
            self._refresh_list()

    def _clear_list(self):
        self._files.clear()
        self._refresh_list()

    def _refresh_list(self):
        self._files.sort(key=lambda p: Path(p).name)
        self._listbox.delete(0, tk.END)
        for path in self._files:
            self._listbox.insert(tk.END, f"  {Path(path).name}")
        n = len(self._files)
        if n == 0:
            self._status.set("Adicione arquivos .txt para formatar.")
        elif n == 1:
            self._status.set("1 arquivo selecionado.")
        else:
            self._status.set(f"{n} arquivos selecionados — serão mesclados em ordem cronológica.")

    def _start(self):
        if not self._files:
            messagebox.showwarning("Heimdall", "Adicione pelo menos um arquivo .txt.", parent=self)
            return

        self._btn.configure(state="disabled")
        self._progress.start()
        self._clear_preview()

        model = self._model_var.get().strip() or "llama3.2"
        threading.Thread(target=self._run, args=(list(self._files), model), daemon=True).start()

    def _run(self, paths, model):
        try:
            output = format_transcription(
                paths,
                model=model,
                on_progress=lambda msg: self.after(0, lambda m=msg: self._status.set(m)),
                on_token=lambda tok: self.after(0, lambda t=tok: self._append_token(t)),
            )
            self.after(0, lambda: self._done(output))
        except Exception as e:
            self.after(0, lambda err=e: self._error(str(err)))

    def _append_token(self, token):
        self._preview.configure(state="normal")
        self._preview.insert("end", token)
        self._preview.see("end")
        self._preview.configure(state="disabled")

    def _clear_preview(self):
        self._preview.configure(state="normal")
        self._preview.delete("1.0", "end")
        self._preview.configure(state="disabled")

    def _done(self, output_path):
        self._progress.stop()
        self._progress.set(1)
        self._btn.configure(state="normal")
        self._status.set(f"Salvo: {output_path}")
        messagebox.showinfo("Heimdall", f"Formatação concluída!\n\n{output_path}", parent=self)

    def _error(self, msg):
        self._progress.stop()
        self._progress.set(0)
        self._btn.configure(state="normal")
        self._status.set(f"Erro: {msg}")
        messagebox.showerror("Heimdall", msg, parent=self)


# ======================================================================

def main():
    app = HeimdallApp()
    app.mainloop()


if __name__ == "__main__":
    main()
