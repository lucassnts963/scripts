#!/usr/bin/env bash
# Backup diário em CSV da base de medição do contrato Trocador de Calor 4600014468.
# Exporta todas as tabelas do SQLite para backup/AAAA-MM-DD/ e apaga backups com mais de 60 dias.
set -euo pipefail
MEDICAO="${MEDICAO_DIR:-/vault/projects/montisol/assets/medicao}"
exec python3 -I "$MEDICAO/medicao.py" backup --manter "${1:-60}"
