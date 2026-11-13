#!/usr/bin/env bash
# Sincroniza os envios do app RDO aprovados no n8n com a base de medição (SQLite).
# Só registra linhas com status "aprovado"; depois marca "registrado" no n8n. Precisa de N8N_API_KEY no ambiente.
# precisa: N8N_API_KEY
set -euo pipefail
MEDICAO="${MEDICAO_DIR:-/vault/projects/montisol/assets/medicao}"
exec python3 -I "$MEDICAO/medicao.py" sincronizar-n8n "$@"
