---
name: montisol-medicao
description: Sincroniza os RDO aprovados do n8n com a base de medição do Trocador (Montisol) e faz o backup dela. Use quando o Lucas disser "sincroniza a medição", "puxa os RDO", "quantos RDO pendentes", "atualiza a medição" ou "backup da medição".
---

# Medição do Trocador (Montisol)

Dois scripts deste repositório cuidam da base de medição do Trocador (um SQLite no vault):

- **sincronizar:** traz do n8n interno (a tabela montisol_rdo_recebidos) os envios do app RDO que o Lucas aprovou, registra cada um na base de medição e marca "registrado" no n8n. Mostra quantos ainda estão pendentes. Grava em `projects/montisol/assets/medicao/dados/`.
- **backup:** copia a base para CSV em `projects/montisol/assets/medicao/backup/AAAA-MM-DD/` e apaga os backups com mais de 60 dias.

## Regras (é dado da Montisol)

- Rode só pelo script_run, com a chamada exata abaixo. Ele pede o "pode" do Lucas, a não ser que ele tenha marcado o script como confiável (aí roda sem perguntar). Nunca rode pelo terminal, nem copie o que o script faz em outra ferramenta.
- O agendamento só roda o script confiável. Se a medição parou ("recusada: o script mudou" ou "nunca foi marcado como confiável"), peça ao Lucas para confiar de novo: rodar o script uma vez por você e responder "sempre" no cartão.
- Nada vai para terceiros. O script só fala com o n8n interno, e o resultado vai só para o Lucas.
- Depois de rodar, diga ao Lucas o que mudou, com os números da saída: quantos RDO foram registrados agora e quantos continuam pendentes. Se falhou, diga o erro como veio, sem tentar outro caminho.

## Sincronizar os RDO aprovados

```script_run
{ "rel": "montisol/medicao-sincronizar.sh", "args": [] }
```
precisa: N8N_API_KEY

## Fazer o backup

```script_run
{ "rel": "montisol/medicao-backup.sh", "args": [] }
```
precisa: nada
