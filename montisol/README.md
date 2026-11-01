# montisol

Backup diário em CSV da base de medição do Trocador (SQLite) em projects/montisol/assets/medicao/backup/AAAA-MM-DD/, guardando 60 dias

## Scripts

- `medicao-backup.sh` — Backup diário em CSV da base de medição do Trocador (SQLite) em projects/montisol/assets/medicao/backup/AAAA-MM-DD/, guardando 60 dias
- `medicao-sincronizar.sh` — Traz do n8n (tabela montisol_rdo_recebidos) os envios do app RDO que o Lucas aprovou e registra na base de medição; mostra quantos estão pendentes
