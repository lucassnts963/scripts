#!/usr/bin/env python3
import argparse
import os
import sys
import warnings
from pathlib import Path

DEFAULT_VOCAB_PATH = Path(__file__).resolve().parent / "vocabulario.txt"

# Avisos conhecidos e inofensivos do pyannote.audio, sem relação com a
# qualidade do resultado: TF32 desativado de propósito (reprodutibilidade) e
# std() com poucas amostras em trechos curtos/quase silenciosos. Filtrados
# pela mensagem para não esconder outros warnings genuínos.
warnings.filterwarnings("ignore", message=r"TensorFloat-32", category=UserWarning)
warnings.filterwarnings("ignore", message=r"std\(\): degrees of freedom", category=UserWarning)


def resolve_hf_token(cli_token):
    return (
        cli_token
        or os.environ.get("HF_TOKEN")
        or os.environ.get("HUGGINGFACE_TOKEN")
        or os.environ.get("HUGGINGFACE_HUB_TOKEN")
    )


def load_vocabulary(vocab_path):
    if not vocab_path or not vocab_path.is_file():
        return None
    termos = []
    for linha in vocab_path.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        termos.append(linha)
    return ", ".join(termos) if termos else None


def run_diarization(audio_array, sample_rate, device, hf_token, num_speakers, min_speakers, max_speakers):
    # Sem token: assume que o modelo já foi baixado em uma execução anterior
    # e força modo 100% local (sem tocar a rede), em vez de tentar ir à internet.
    # Precisa ser definida ANTES de importar pyannote.audio/huggingface_hub,
    # pois essas libs leem a variável de ambiente uma única vez, na importação.
    offline = not hf_token
    if offline:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")

    try:
        from pyannote.audio import Pipeline
    except ImportError:
        sys.exit(
            "[!] Erro: pyannote.audio não está instalado.\n"
            "    Instale com: pip install -r requirements.txt"
        )

    if offline:
        print("[*] Carregando pipeline de diarização (modo offline, usando cache local)...")
    else:
        print("[*] Carregando pipeline de diarização (pyannote.audio)...")

    try:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", token=hf_token
        )
    except Exception as exc:
        if offline:
            sys.exit(
                "[!] Erro: modelo de diarização não encontrado no cache local e nenhum token foi informado.\n"
                "    Rode uma vez com internet e --hf-token (ou variável de ambiente HF_TOKEN) para baixar\n"
                "    e cachear o modelo. Depois disso, as próximas execuções funcionam offline, sem token.\n"
                f"    Detalhe: {exc}"
            )
        sys.exit(f"[!] Erro ao carregar o pipeline de diarização: {exc}")

    if pipeline is None:
        sys.exit(
            "[!] Erro: não foi possível carregar o pipeline de diarização.\n"
            "    Verifique se você aceitou os termos de uso em:\n"
            "    https://huggingface.co/pyannote/speaker-diarization-3.1\n"
            "    https://huggingface.co/pyannote/segmentation-3.0\n"
            "    e se o token informado (--hf-token ou HF_TOKEN) é válido."
        )

    import torch

    print(f"[*] Diarização em: {device.upper()}")
    if device == "cuda":
        pipeline.to(torch.device("cuda"))

    kwargs = {}
    if num_speakers:
        kwargs["num_speakers"] = num_speakers
    else:
        if min_speakers:
            kwargs["min_speakers"] = min_speakers
        if max_speakers:
            kwargs["max_speakers"] = max_speakers

    # Áudio já decodificado em memória (via PyAV, no faster-whisper) é passado
    # diretamente como waveform, em vez do caminho do arquivo: o pyannote.audio 4.x
    # usa torchcodec para ler arquivos do disco, que por sua vez exige FFmpeg
    # instalado no sistema operacional. Passando a waveform pronta, esse passo
    # (e a dependência de FFmpeg no sistema) é evitado por completo.
    waveform = torch.from_numpy(audio_array).unsqueeze(0)

    print("[*] Identificando falantes...")
    # ProgressHook mostra uma barra de progresso por etapa (segmentação,
    # embeddings, clustering, etc.) — sem isso, áudios longos ficam vários
    # minutos sem nenhuma saída no console, parecendo travado.
    from pyannote.audio.pipelines.utils.hook import ProgressHook

    with ProgressHook() as hook:
        output = pipeline({"waveform": waveform, "sample_rate": sample_rate}, hook=hook, **kwargs)
    # pyannote.audio 4.x retorna um DiarizeOutput (dataclass); versões 3.x
    # retornavam a Annotation diretamente. Suporta os dois formatos.
    annotation = getattr(output, "speaker_diarization", output)
    turns = [
        (turn.start, turn.end, speaker)
        for turn, _, speaker in annotation.itertracks(yield_label=True)
    ]

    if device == "cuda":
        # A VRAM usada pelo pipeline de diarização fica "reservada" pelo torch
        # mesmo depois de pronta. Em GPUs pequenas (ex: 2GB), isso pode não
        # deixar espaço suficiente para o modelo do Whisper rodar em seguida
        # também na GPU. Libera explicitamente antes de seguir.
        del pipeline, output
        torch.cuda.empty_cache()

    return turns


def speaker_at(turns, start, end):
    best_speaker, best_overlap = None, 0.0
    for t_start, t_end, speaker in turns:
        overlap = min(end, t_end) - max(start, t_start)
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = speaker
    return best_speaker


def parse_speaker_names(raw):
    mapping = {}
    if not raw:
        return mapping
    for pair in raw.split(","):
        if "=" not in pair:
            continue
        old, new = pair.split("=", 1)
        old, new = old.strip(), new.strip()
        if old and new:
            mapping[old] = new
    return mapping


def prompt_speaker_names(speakers, presets):
    mapping = dict(presets)
    remaining = [s for s in speakers if s not in mapping]
    if not remaining:
        return mapping

    print("\n[*] Falantes detectados. Digite um nome e pressione Enter (Enter em branco mantém o padrão).")
    for speaker in remaining:
        try:
            new_name = input(f"    {speaker} -> ").strip()
        except EOFError:
            new_name = ""
        mapping[speaker] = new_name or speaker

    # Revisão: evita ter que reprocessar tudo de novo só por causa de um erro
    # de digitação num nome.
    while True:
        print("\n[*] Confira os nomes:")
        for i, s in enumerate(speakers, 1):
            print(f"    {i}. {s} -> {mapping[s]}")
        try:
            resposta = input("Tudo certo? Enter para confirmar, ou o número do falante pra corrigir: ").strip()
        except EOFError:
            resposta = ""
        if not resposta:
            break
        if resposta.isdigit() and 1 <= int(resposta) <= len(speakers):
            s = speakers[int(resposta) - 1]
            try:
                novo = input(f"    Novo nome para {s} -> ").strip()
            except EOFError:
                novo = ""
            mapping[s] = novo or s
        else:
            print("    [!] Digite o número de um falante da lista, ou apenas Enter.")

    return mapping


def main():
    parser = argparse.ArgumentParser(
        prog="transcribe",
        description="CLI multiplataforma para transcrição de áudio com faster-whisper, com identificação opcional de falantes (pyannote.audio)."
    )

    parser.add_argument("audio", type=str, help="Caminho do arquivo de áudio (realtivo ou absoluto)")
    parser.add_argument("-m", "--model", default="base", choices=["tiny", "base", "small", "medium", "large-v3"], help="Tamanho do modelo (padrão: base)")
    parser.add_argument("-d", "--device", default="auto", choices=["auto", "cpu", "cuda"], help="Dispositivo de execução, usado para a transcrição e (se não sobrescrito por --diarize-device) também para a diarização (padrão: auto")
    parser.add_argument("--diarize-device", default=None, choices=["auto", "cpu", "cuda"], help="Dispositivo só para a diarização, se quiser diferente de --device (útil em GPUs pequenas, p/ não rodar Whisper e diarização na GPU ao mesmo tempo). Padrão: usa o mesmo valor de --device")
    parser.add_argument("-l", "--lang", default=None, help="Código do idioma (ex: 'pt', 'en'). Padrão: detecção automática")
    parser.add_argument("-o", "--output", default=None, help="Caminho de saída .txt (padrão: mesmo dirtório e nome do áudio")
    parser.add_argument("--timestamps", action="store_true", help="Salva os timestamps no arquivo gerado")

    parser.add_argument("--vocab", default=None, help=f"Arquivo de vocabulário para melhorar o reconhecimento de nomes/termos, um por linha (padrão: {DEFAULT_VOCAB_PATH.name} na pasta do script, se existir)")
    parser.add_argument("--no-vocab", action="store_true", help="Não usar o arquivo de vocabulário, mesmo que exista")

    parser.add_argument("--diarize", action="store_true", help="Identifica os diferentes falantes no áudio (usa pyannote.audio)")
    parser.add_argument("--hf-token", default=None, help="Token do Hugging Face, necessário só na primeira vez para baixar o modelo de diarização (ou defina a variável de ambiente HF_TOKEN). Depois do primeiro download, roda offline sem token")
    parser.add_argument("--num-speakers", type=int, default=None, help="Número exato de falantes, se conhecido")
    parser.add_argument("--min-speakers", type=int, default=None, help="Número mínimo de falantes esperado")
    parser.add_argument("--max-speakers", type=int, default=None, help="Número máximo de falantes esperado")
    parser.add_argument("--speaker-names", default=None, help="Mapeamento de nomes no formato 'SPEAKER_00=Ana,SPEAKER_01=Bruno'")
    parser.add_argument("--no-rename", action="store_true", help="Não perguntar os nomes dos falantes interativamente (usa apenas --speaker-names, se houver)")

    args = parser.parse_args()

    audio_file = Path(args.audio).expanduser().resolve()
    if not audio_file.is_file():
        sys.exit(f"[!] Erro: Arquivo não encontrado -> {audio_file}")

    def resolve_device(escolha):
        if escolha == "auto":
            try:
                import torch
                return "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                return "cpu"
        return escolha

    device = resolve_device(args.device)
    diarize_device = resolve_device(args.diarize_device) if args.diarize_device else device

    if device == "cuda" or diarize_device == "cuda":
        # No Windows, o ctranslate2 (usado pelo faster-whisper) depende da
        # cublas64_12.dll do CUDA, mas só a encontra se alguém já tiver
        # registrado o diretório de DLLs do torch no processo antes. Sem isso,
        # "-d cuda" sem --diarize falha com "Library cublas64_12.dll is not
        # found", já que só importávamos torch dentro da diarização.
        import torch  # noqa: F401

    compute_type = "float16" if device == "cuda" else "int8"

    hf_token = None
    if args.diarize:
        hf_token = resolve_hf_token(args.hf_token)
        if not hf_token:
            # Assume que o modelo já foi baixado em uma execução anterior e força
            # modo 100% local. Precisa ser definida ANTES de importar faster_whisper
            # ou pyannote.audio: ambos carregam o huggingface_hub internamente, que
            # só lê essa variável de ambiente uma única vez, na primeira importação.
            os.environ.setdefault("HF_HUB_OFFLINE", "1")

    from faster_whisper import decode_audio, WhisperModel

    print(f"[*] Lendo áudio: {audio_file.name}...")
    sample_rate = 16000
    audio_array = decode_audio(str(audio_file), sampling_rate=sample_rate)

    turns = None
    if args.diarize:
        turns = run_diarization(
            audio_array, sample_rate, diarize_device, hf_token,
            args.num_speakers, args.min_speakers, args.max_speakers
        )

    hotwords = None
    if not args.no_vocab:
        vocab_path = Path(args.vocab).expanduser().resolve() if args.vocab else DEFAULT_VOCAB_PATH
        hotwords = load_vocabulary(vocab_path)
        if hotwords:
            print(f"[*] Vocabulário: {vocab_path.name} ({len(hotwords.split(', '))} termos)")

    print(f"[*] Modelo: {args.model} | Device: {device.upper()} ({compute_type})")
    model = WhisperModel(args.model, device=device, compute_type=compute_type)

    print(f"[*] Processamento: {audio_file.name}...")
    segments, info = model.transcribe(
        audio_array,
        beam_size=5,
        language=args.lang,
        hotwords=hotwords,
        log_progress=True,
        # Em áudio real (várias pessoas falando por cima, ruído, trechos
        # incertos), o Whisper pode entrar num loop repetindo a mesma
        # palavra/frase dezenas de vezes. condition_on_previous_text=False
        # evita que um erro contamine o resto do áudio (cada trecho de ~30s
        # é decodificado sem depender do texto anterior); no_repeat_ngram_size
        # bloqueia diretamente a repetição da mesma sequência de 3 palavras;
        # vad_filter pula trechos sem fala, que são o gatilho mais comum
        # dessas alucinações.
        condition_on_previous_text=False,
        no_repeat_ngram_size=3,
        vad_filter=True
    )

    detected_lang = args.lang or f"{info.language} ({info.language_probability:1%})"
    print(f"[*] Idioma: {detected_lang} | Duração: {info.duration:.1f}s\n")

    resultados = []
    for segment in segments:
        stamp = f"[{segment.start:05.1f}s -> {segment.end:05.1f}s]"
        text = segment.text.strip()
        speaker = speaker_at(turns, segment.start, segment.end) if turns is not None else None

        if speaker:
            print(f"{stamp} {speaker}: {text}")
        else:
            print(f"{stamp} {text}")

        resultados.append({"stamp": stamp, "text": text, "speaker": speaker})

    speaker_map = parse_speaker_names(args.speaker_names)
    if args.diarize and not args.no_rename:
        detected_speakers = sorted({r["speaker"] for r in resultados if r["speaker"]})
        speaker_map = prompt_speaker_names(detected_speakers, speaker_map)

    linhas = []
    if args.diarize:
        last_speaker = None
        for r in resultados:
            nome = speaker_map.get(r["speaker"], r["speaker"] or "Desconhecido")
            prefixo = f"{r['stamp']} " if args.timestamps else ""
            if nome != last_speaker:
                if linhas:
                    linhas.append("")
                linhas.append(f"{prefixo}{nome}: {r['text']}")
                last_speaker = nome
            else:
                linhas.append(f"{prefixo}{r['text']}")
        out_content = "\n".join(linhas)
    else:
        for r in resultados:
            linhas.append(f"{r['stamp']} {r['text']}" if args.timestamps else r["text"])
        out_content = "\n".join(linhas) if args.timestamps else " ".join(linhas)

    out_path = Path(args.output).expanduser().resolve() if args.output else audio_file.with_suffix(".txt")
    out_path.write_text(out_content, encoding="utf-8")

    print(f"\n[✓] Concluído: {out_path}")

if __name__ == "__main__":
    main()
