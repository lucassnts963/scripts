#!/usr/bin/env bash
# Backup diário em CSV da base de medição do contrato Trocador de Calor 4600014468.
# Exporta todas as tabelas do SQLite para backup/AAAA-MM-DD/ e apaga backups com mais de 60 dias.
# usa: montisol/medicao.py
set -euo pipefail
# o código vem do repositório (ao lado deste arquivo); os dados ficam no vault
CODIGO="$(cd "$(dirname "$0")" && pwd)"
export MEDICAO_DIR="${MEDICAO_DIR:-/vault/projects/montisol/assets/medicao}"
MEDICAO="$MEDICAO_DIR"
exec python3 -I "$CODIGO/medicao.py" backup --manter "${1:-60}"
