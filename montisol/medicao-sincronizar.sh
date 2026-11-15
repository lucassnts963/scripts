#!/usr/bin/env bash
# Sincroniza os envios do app RDO aprovados no n8n com a base de medição (SQLite).
# Só registra linhas com status "aprovado"; depois marca "registrado" no n8n. Precisa de N8N_API_KEY no ambiente.
# precisa: N8N_API_KEY
# usa: montisol/medicao.py
# rede: n8n
set -euo pipefail
# o código vem do repositório (ao lado deste arquivo); os dados ficam no vault
CODIGO="$(cd "$(dirname "$0")" && pwd)"
export MEDICAO_DIR="${MEDICAO_DIR:-/vault/projects/montisol/assets/medicao}"
MEDICAO="$MEDICAO_DIR"
exec python3 -I "$CODIGO/medicao.py" sincronizar-n8n "$@"
