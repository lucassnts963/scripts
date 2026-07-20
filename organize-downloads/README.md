# organize-downloads

Organiza uma pasta (por padrão a de **Downloads**) movendo cada arquivo para uma
subpasta de acordo com o tipo: `Imagens`, `Documentos`, `Videos`, `Audio`,
`Compactados`, `Programas`, `Codigo` e `Outros`.

- Sem dependências — usa só os módulos nativos do Node.
- **Idempotente**: rodar de novo não quebra nada (as subpastas de categoria já criadas são ignoradas).
- Trata colisão de nomes acrescentando ` (1)`, ` (2)`, ... antes da extensão.
- Multiplataforma (Windows, Linux, macOS). Move entre volumes diferentes copiando + apagando.

## Uso

```bash
# organiza a ~/Downloads do usuário
node organize-downloads.js

# ver o que aconteceria, sem mover nada
node organize-downloads.js --dry-run

# organizar outra pasta
node organize-downloads.js --dir "D:/Baixados"
```

## Opções

| Opção | Descrição |
|-------|-----------|
| `-d`, `--dir <caminho>` | Pasta a organizar (padrão: `~/Downloads`). |
| `-n`, `--dry-run` | Só mostra o que faria, sem mover nada. |
| `-h`, `--help` | Mostra a ajuda. |

## Categorias

As extensões de cada categoria estão no topo do
[`organize-downloads.js`](./organize-downloads.js), na constante `CATEGORIES` —
é só editar a lista para incluir ou remover extensões. Qualquer extensão não
mapeada (ou arquivo sem extensão) vai para `Outros`. Arquivos ocultos (começando
com `.`) são ignorados.

## Dica: rodar de qualquer lugar

```bash
# alias (Linux/macOS)
alias organize-downloads='node /caminho/para/scripts/organize-downloads/organize-downloads.js'
```
