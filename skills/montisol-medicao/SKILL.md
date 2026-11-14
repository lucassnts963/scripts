---
name: montisol-medicao
description: A base de medição do Trocador (Montisol): sincronizar os RDO aprovados do n8n, ler as mensagens do WhatsApp da base, conferir, gerar a planilha de controle, a análise e o backup. Use quando o Lucas ou a rotina da medição pedirem "sincroniza a medição", "puxa os RDO", "lê o WhatsApp da base", "confere a medição", "gera a planilha", "análise da medição" ou "backup da medição".
---

# Medição do Trocador (Montisol)

Três scripts deste repositório cuidam da base de medição do Trocador (um SQLite no vault):

- **sincronizar:** traz do n8n interno (a tabela montisol_rdo_recebidos) os envios do app RDO que o Lucas aprovou, registra cada um na base de medição e marca "registrado" no n8n. Mostra quantos ainda estão pendentes. Grava em `projects/montisol/assets/medicao/dados/`.
- **backup:** copia a base para CSV em `projects/montisol/assets/medicao/backup/AAAA-MM-DD/` e apaga os backups com mais de 60 dias.
- **medicao.sh:** os comandos do dia a dia, só de uma lista fechada: `conferir`, `planilha`, `whatsapp` e `analise`. Qualquer outro comando ou argumento é recusado. Grava só em `projects/montisol/assets/medicao/dados/`.

## Regras (é dado da Montisol)

- Rode só pelo script_run, com a chamada exata abaixo. O terminal não serve: na caixa de areia o vault é só leitura, e a base dá "unable to open database file". Ele pede o "pode" do Lucas, a não ser que ele tenha marcado o script como confiável (aí roda sem perguntar). Nunca rode pelo terminal, nem copie o que o script faz em outra ferramenta.
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

## A entrada do WhatsApp

O `whatsapp` lê só um arquivo **direto em** `projects/montisol/assets/medicao/dados/entrada/`. Nunca passe outro caminho.

1. Leia as mensagens novas com o `wa_fila`.
2. Grave o texto com o **Write** em `projects/montisol/assets/medicao/dados/entrada/wa-AAAA-MM-DD-HHh.txt`. O nome tem só letras, números, ponto, `-` e `_`.
3. Rode o `whatsapp` passando **só o nome do arquivo**:

```script_run
{ "rel": "montisol/medicao.sh", "args": ["whatsapp", "wa-AAAA-MM-DD-HHh.txt"] }
```
precisa: nada

Com o grupo: `["whatsapp", "wa-AAAA-MM-DD-HHh.txt", "--grupo", "<grupo>"]`.

## Conferir a base

```script_run
{ "rel": "montisol/medicao.sh", "args": ["conferir", "--periodo", "3"] }
```
precisa: nada

Sem o período: `["conferir"]`.

## Gerar a planilha de controle

```script_run
{ "rel": "montisol/medicao.sh", "args": ["planilha"] }
```
precisa: nada

A planilha sai sempre em `projects/montisol/assets/medicao/dados/controle-medicao-trocador-4600014468.xlsx`. O script não aceita outro destino.

## A análise

```script_run
{ "rel": "montisol/medicao.sh", "args": ["analise"] }
```
precisa: nada

## Se der "recusada" ou pedir o "pode"

O `medicao.sh` é um script novo. Na primeira vez, o script_run pede o "pode" do Lucas. Peça a ele para responder **"sempre"**: depois disso, a rotina roda sem perguntar até o código mudar.
