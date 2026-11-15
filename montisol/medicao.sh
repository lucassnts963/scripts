#!/usr/bin/env bash
# Roda um comando da base de medição do Trocador (Montisol), só de uma lista fechada:
#   conferir [--periodo N]            confere a base (N = número do período)
#   planilha                          gera a planilha de controle em dados/ (nunca outro lugar)
#   whatsapp <arquivo> [--grupo G]    lê o texto do WhatsApp salvo em dados/entrada/<arquivo>
#   analise                           a análise da base
# Qualquer outro subcomando ou argumento é recusado. Grava só em dados/.
# precisa: nada
# usa: montisol/medicao.py
set -euo pipefail
# o código vem do repositório (ao lado deste arquivo); os dados ficam no vault
CODIGO="$(cd "$(dirname "$0")" && pwd)"
export MEDICAO_DIR="${MEDICAO_DIR:-/vault/projects/montisol/assets/medicao}"
MEDICAO="$MEDICAO_DIR"
DADOS="$MEDICAO/dados"
ENTRADA="$DADOS/entrada"
PY=(python3 -I "$CODIGO/medicao.py")

recusa() { echo "medicao.sh: $*" >&2; exit 2; }

# um argumento de texto: sem caminho absoluto, sem "..", sem começar com "-" (exceto as opções aceitas)
texto_ok() {
  case "$1" in
    "" | /* | *..* ) return 1 ;;
  esac
  return 0
}

[ $# -ge 1 ] || recusa "falta o subcomando (conferir, planilha, whatsapp ou analise)"
sub="$1"; shift

case "$sub" in
  conferir)
    if [ $# -eq 0 ]; then
      exec "${PY[@]}" conferir
    fi
    [ $# -eq 2 ] && [ "$1" = "--periodo" ] || recusa "conferir aceita só --periodo N"
    [[ "$2" =~ ^[0-9]{1,3}$ ]] || recusa "o período é um número"
    exec "${PY[@]}" conferir --periodo "$2"
    ;;
  planilha)
    [ $# -eq 0 ] || recusa "planilha não aceita argumentos (a saída é sempre em dados/)"
    exec "${PY[@]}" planilha --saida "$DADOS/controle-medicao-trocador-4600014468.xlsx"
    ;;
  whatsapp)
    [ $# -eq 1 ] || [ $# -eq 3 ] || recusa "whatsapp <arquivo> [--grupo G]"
    nome="$1"
    [[ "$nome" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || recusa "o arquivo é só um nome dentro de dados/entrada/ (letras, números, ponto, - e _)"
    texto_ok "$nome" || recusa "nome de arquivo inválido"
    arq="$ENTRADA/$nome"
    [ -f "$arq" ] && [ ! -L "$arq" ] || recusa "não achei $nome em dados/entrada/ (salve o texto lá pelo Write)"
    real="$(realpath -e "$arq")"
    base="$(realpath -e "$ENTRADA")"
    [ "${real%/*}" = "$base" ] || recusa "o arquivo precisa estar direto em dados/entrada/"
    if [ $# -eq 3 ]; then
      [ "$2" = "--grupo" ] || recusa "whatsapp aceita só --grupo depois do arquivo"
      grupo="$3"
      texto_ok "$grupo" || recusa "grupo inválido"
      [ "${#grupo}" -le 80 ] || recusa "grupo longo demais"
      exec "${PY[@]}" whatsapp "$real" --grupo "$grupo"
    fi
    exec "${PY[@]}" whatsapp "$real"
    ;;
  analise)
    [ $# -eq 0 ] || recusa "analise não aceita argumentos"
    exec "${PY[@]}" analise
    ;;
  *)
    recusa "subcomando não aceito: $sub (só conferir, planilha, whatsapp ou analise)"
    ;;
esac
