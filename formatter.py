from pathlib import Path

import ollama

SYSTEM_PROMPT = """\
Você é um assistente especializado em formatar transcrições de aulas e vídeos em Markdown.

Regras obrigatórias:
- NÃO altere, resuma ou omita nenhuma informação do texto original.
- Apenas reorganize e formate — as palavras devem ser as mesmas.
- Remova as marcações de horário no formato [HH:MM:SS].
- Identifique mudanças de tema e crie títulos (##) e subtítulos (###) adequados.
- Use listas com bullet points (- ) para enumerações, conceitos e itens paralelos.
- Agrupe frases relacionadas em parágrafos coesos.
- Mantenha a ordem cronológica do conteúdo.
- Responda APENAS com o conteúdo Markdown formatado, sem comentários ou explicações.\
"""

DEFAULT_MODEL = "llama3.2"


def _clean_raw(content: str) -> str:
    """Remove cabeçalhos/rodapés gerados pelo Heimdall."""
    lines = [l for l in content.splitlines() if not l.strip().startswith("===")]
    return "\n".join(lines).strip()


def format_transcription(txt_paths: list, model: str = DEFAULT_MODEL, on_progress=None, on_token=None) -> str:
    """
    Formata um ou mais arquivos .txt de transcrição e salva como .md.
    Quando múltiplos arquivos são passados, são mesclados em ordem cronológica
    (ordenação pelo nome do arquivo).

    Args:
        txt_paths:   Lista de caminhos para arquivos .txt.
        model:       Modelo Ollama a usar (ex: llama3.2, qwen2.5, mistral).
        on_progress: Callback opcional chamado com mensagens de status (str).
        on_token:    Callback opcional chamado com cada token gerado (str).

    Returns:
        Caminho do arquivo .md gerado.

    Raises:
        ConnectionError: Se o Ollama não estiver rodando.
        FileNotFoundError: Se algum arquivo não existir.
    """
    paths = sorted([Path(p) for p in txt_paths], key=lambda p: p.name)

    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {path}")

    if on_progress:
        on_progress(f"Lendo {len(paths)} arquivo(s)...")

    parts = []
    for path in paths:
        content = path.read_text(encoding="utf-8")
        clean = _clean_raw(content)
        if clean:
            parts.append(clean)

    combined = "\n\n".join(parts)

    if not combined.strip():
        raise ValueError("Os arquivos estão vazios ou contêm apenas cabeçalhos.")

    if on_progress:
        on_progress(f"Gerando formatação com '{model}'...")

    try:
        stream = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Formate esta transcrição:\n\n{combined}"},
            ],
            stream=True,
        )
    except Exception as e:
        raise ConnectionError(
            f"Não foi possível conectar ao Ollama: {e}\n\n"
            "Verifique se o Ollama está rodando (execute 'ollama serve' no terminal)."
        ) from e

    tokens = []
    for chunk in stream:
        token = chunk["message"]["content"]
        tokens.append(token)
        if on_token:
            on_token(token)

    formatted = "".join(tokens).strip()

    # Salva com o nome do primeiro arquivo (mais antigo)
    output_path = paths[0].with_suffix(".md")

    if on_progress:
        on_progress(f"Salvando em {output_path.name}...")

    output_path.write_text(formatted, encoding="utf-8")
    return str(output_path)
