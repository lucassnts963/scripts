#!/usr/bin/env python3
import argparse
import os
import re
import sys
from pathlib import Path

from transcribe import load_vocabulary, DEFAULT_VOCAB_PATH

DEFAULT_API_BASE = "http://localhost:11434/v1"  # Ollama (servidor local, API compatível com OpenAI)
DEFAULT_MODEL = "llama3.1"

SYSTEM_PROMPT = """Você é um assistente que organiza transcrições de reuniões em atas profissionais, em português do Brasil.

Regras importantes:
- Use APENAS as informações presentes na transcrição. Nunca invente participantes, decisões, prazos ou dados que não estejam no texto.
- Se a transcrição tiver falantes identificados (nomes antes de ":"), use-os para listar os participantes e atribuir falas/ações a eles.
- Se não houver identificação de falantes, não invente nomes; escreva "Não identificado".
- Se a informação de alguma seção não existir na transcrição, escreva "Não mencionado" nessa seção em vez de inventar.
- Seja conciso, organize por tópicos e não copie a transcrição literalmente.

Formate a saída em Markdown, seguindo exatamente esta estrutura:

# Ata de Reunião

## Participantes
- ...

## Resumo
(um parágrafo curto com o propósito e o resultado geral da reunião)

## Principais Tópicos Discutidos
- ...

## Decisões
- ...

## Ações e Responsáveis
- [Responsável] Ação (prazo, se mencionado)

## Próximos Passos
- ...
"""

MAP_PROMPT = """Você vai receber um trecho de uma transcrição de reunião (pode começar ou terminar no meio de uma fala).
Resuma esse trecho em tópicos objetivos (bullet points), preservando: quem falou (se identificado), decisões tomadas,
ações e responsáveis, e pontos importantes discutidos. Não adicione informação que não esteja no texto.
Responda apenas com os tópicos, sem introdução nem conclusão."""

REDUCE_PROMPT_PREFIX = "Abaixo estão notas resumidas de cada trecho de uma mesma reunião, em ordem cronológica. Consolide tudo em uma única ata, sem repetir informação:\n\n"


def build_vocab_note(vocab_terms):
    if not vocab_terms:
        return ""
    return (
        "\n\nVocabulário conhecido (nomes de pessoas, siglas e termos usados nesta organização): "
        f"{vocab_terms}.\n"
        "A transcrição vem de reconhecimento de voz automático e pode ter escrito algum desses termos "
        "errado (troca de letras, grafia parecida foneticamente). Ao reconhecer uma variação óbvia de um "
        "termo da lista, corrija para a grafia acima. Não force nenhum desses termos onde não fizer sentido."
    )


def sanitizar_nome_arquivo(nome):
    """Troca caracteres inválidos em nome de arquivo no Windows (ex: ':' em 'qwen2.5:1.5b') por '-'."""
    return re.sub(r'[\\/:*?"<>|]+', "-", nome).strip("-")


def split_into_chunks(text, max_chars):
    blocos = text.split("\n\n")
    chunks, atual, tamanho_atual = [], [], 0
    for bloco in blocos:
        tamanho_bloco = len(bloco) + 2
        if atual and tamanho_atual + tamanho_bloco > max_chars:
            chunks.append("\n\n".join(atual))
            atual, tamanho_atual = [], 0
        atual.append(bloco)
        tamanho_atual += tamanho_bloco
    if atual:
        chunks.append("\n\n".join(atual))
    return chunks


# (tamanho do n-grama em palavras, quantas repetições seguidas contam como loop).
# LLMs pequenas/quantizadas (ex: qwen2.5:1.5b) tanto travam repetindo uma
# palavra/frase curta quanto — como vimos na prática — um bloco de várias
# falas inteiras (20-30+ palavras) alternando entre os mesmos falantes.
# Blocos maiores repetindo já 3 vezes seguidas são inequivocamente um loop
# (ao contrário de uma palavra curta, que pode legitimamente aparecer
# repetida algumas vezes em fala natural), por isso o limiar cai conforme
# o n-grama cresce.
_FAIXAS_LOOP = [(1, 6, 5), (7, 20, 4), (21, 80, 3)]


def _cauda_repetida(palavras, tam, min_repeticoes):
    total = tam * min_repeticoes
    n = len(palavras)
    if n < total:
        return False
    cauda = palavras[n - total:]
    ngram = cauda[:tam]
    return all(cauda[i:i + tam] == ngram for i in range(0, total, tam))


def detectar_loop(palavras):
    """Detecta se o final da lista de palavras é uma sequência de n-gramas repetidos."""
    for tam_min, tam_max, min_repeticoes in _FAIXAS_LOOP:
        for tam in range(tam_min, tam_max + 1):
            if _cauda_repetida(palavras, tam, min_repeticoes):
                return True
    return False


def truncar_repeticao(texto):
    """Corta o texto no primeiro ponto onde um n-grama se repete várias vezes seguidas."""
    palavras = texto.split()
    n = len(palavras)
    for i in range(n):
        for tam_min, tam_max, min_repeticoes in _FAIXAS_LOOP:
            for tam in range(tam_min, tam_max + 1):
                total = tam * min_repeticoes
                if i + total > n:
                    continue
                ngram = palavras[i:i + tam]
                if all(palavras[i + k * tam:i + (k + 1) * tam] == ngram for k in range(min_repeticoes)):
                    return " ".join(palavras[:i]).strip(), True
    return texto, False


def chat(client, model, system, user, temperature=0.2, frequency_penalty=0.4, presence_penalty=0.2):
    # Streaming em vez de esperar a resposta inteira: sem isso, uma chamada
    # longa a um LLM local fica minutos sem nenhuma saída, parecendo travada
    # (mesmo problema que resolvemos na diarização/transcrição).
    stream = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        # Penalizam tokens repetidos, reduzindo a chance de loop — sem
        # eliminar por completo em modelos muito pequenos, por isso o
        # detector de loop abaixo corta o texto se mesmo assim acontecer.
        frequency_penalty=frequency_penalty,
        presence_penalty=presence_penalty,
        stream=True,
    )

    partes = []
    texto_acumulado = ""
    loop_detectado = False
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if not delta:
            continue

        print(delta, end="", flush=True)
        partes.append(delta)
        texto_acumulado += delta

        palavras = texto_acumulado.split()
        if len(palavras) >= 6 and detectar_loop(palavras):
            loop_detectado = True
            break
    print()

    if loop_detectado:
        stream.close()

    resultado = "".join(partes).strip()

    if loop_detectado:
        resultado, _ = truncar_repeticao(resultado)
        print("[!] Aviso: a LLM entrou em loop de repetição nesse trecho — texto cortado no ponto onde começou.\n")

    return resultado


def gerar_ata(client, model, transcript, chunk_chars, vocab_terms=None):
    vocab_note = build_vocab_note(vocab_terms)
    system_prompt = SYSTEM_PROMPT + vocab_note
    map_prompt = MAP_PROMPT + vocab_note

    if len(transcript) <= chunk_chars:
        print("[*] Gerando ata...")
        return chat(client, model, system_prompt, transcript)

    chunks = split_into_chunks(transcript, chunk_chars)
    print(f"[*] Transcrição longa: dividida em {len(chunks)} trechos.")

    notas = []
    for i, chunk in enumerate(chunks, 1):
        print(f"\n[*] Resumindo trecho {i}/{len(chunks)}...")
        notas.append(f"--- Trecho {i} ---\n{chat(client, model, map_prompt, chunk)}")

    print("\n[*] Consolidando ata final...")
    combinado = REDUCE_PROMPT_PREFIX + "\n\n".join(notas)
    return chat(client, model, system_prompt, combinado)


def main():
    parser = argparse.ArgumentParser(
        prog="ata",
        description="Gera uma ata de reunião a partir de uma transcrição (.txt), usando um LLM local ou qualquer API compatível com OpenAI."
    )

    parser.add_argument("transcricao", type=str, help="Caminho do arquivo de transcrição (.txt gerado pelo transcribe.py)")
    parser.add_argument("-m", "--model", default=os.environ.get("ATA_MODEL", DEFAULT_MODEL), help=f"Nome do modelo a usar no servidor (padrão: {DEFAULT_MODEL})")
    parser.add_argument("--api-base", default=os.environ.get("ATA_API_BASE", DEFAULT_API_BASE), help=f"URL base da API compatível com OpenAI (padrão: {DEFAULT_API_BASE}, servidor local do Ollama). LM Studio: http://localhost:1234/v1. NVIDIA API (build.nvidia.com): https://integrate.api.nvidia.com/v1. OpenAI: https://api.openai.com/v1")
    parser.add_argument("--api-key", default=os.environ.get("ATA_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("NVIDIA_API_KEY"), help="Chave de API (necessária para OpenAI, NVIDIA API e outros serviços remotos; servidores locais geralmente ignoram). Também pode ser definida via ATA_API_KEY, OPENAI_API_KEY ou NVIDIA_API_KEY")
    parser.add_argument("-o", "--output", default=None, help="Caminho de saída .md (padrão: <transcricao>_ata.md)")
    parser.add_argument("--chunk-chars", type=int, default=12000, help="Tamanho máximo, em caracteres, de cada trecho enviado ao modelo em transcrições longas (padrão: 12000)")
    parser.add_argument("--vocab", default=None, help=f"Arquivo de vocabulário (mesmo do transcribe.py) para a LLM corrigir nomes/termos na ata (padrão: {DEFAULT_VOCAB_PATH.name} na pasta do script, se existir)")
    parser.add_argument("--no-vocab", action="store_true", help="Não usar o arquivo de vocabulário, mesmo que exista")

    args = parser.parse_args()

    txt_path = Path(args.transcricao).expanduser().resolve()
    if not txt_path.is_file():
        sys.exit(f"[!] Erro: Arquivo não encontrado -> {txt_path}")

    transcript = txt_path.read_text(encoding="utf-8").strip()
    if not transcript:
        sys.exit(f"[!] Erro: Arquivo de transcrição vazio -> {txt_path}")

    vocab_terms = None
    if not args.no_vocab:
        vocab_path = Path(args.vocab).expanduser().resolve() if args.vocab else DEFAULT_VOCAB_PATH
        vocab_terms = load_vocabulary(vocab_path)
        if vocab_terms:
            print(f"[*] Vocabulário: {vocab_path.name} ({len(vocab_terms.split(', '))} termos)")

    try:
        from openai import OpenAI
    except ImportError:
        sys.exit(
            "[!] Erro: pacote 'openai' não está instalado.\n"
            "    Instale com: pip install -r requirements.txt"
        )

    client = OpenAI(base_url=args.api_base, api_key=args.api_key or "local", timeout=120.0, max_retries=1)

    print(f"[*] Modelo: {args.model} | Endpoint: {args.api_base}")

    try:
        ata = gerar_ata(client, args.model, transcript, args.chunk_chars, vocab_terms)
    except Exception as exc:
        sys.exit(
            "[!] Erro ao chamar o modelo de linguagem.\n"
            f"    Endpoint: {args.api_base}\n"
            "    Se estiver usando um servidor local (ex: Ollama), verifique se ele está rodando\n"
            "    e se o modelo foi baixado (ex: 'ollama serve' e 'ollama pull llama3.1').\n"
            "    Para usar outro serviço, informe --api-base e --api-key.\n"
            f"    Detalhe: {exc}"
        )

    if args.output:
        out_path = Path(args.output).expanduser().resolve()
    else:
        modelo_seguro = sanitizar_nome_arquivo(args.model)
        out_path = txt_path.with_name(f"{txt_path.stem}_ata_{modelo_seguro}.md")
    out_path.write_text(ata, encoding="utf-8")

    print(f"\n[✓] Ata gerada: {out_path}")


if __name__ == "__main__":
    main()
