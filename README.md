# scripts

Coleção de scripts úteis que uso no dia a dia para automatizar e facilitar meu trabalho.
Organizados por categoria — cada pasta agrupa scripts de um mesmo tema e traz um README
explicando o que cada um faz e como usar.

## Categorias

| Categoria | Descrição |
|-----------|-----------|
| [`ubuntu-setup/`](./ubuntu-setup) | Scripts de pós-instalação e configuração de um Ubuntu novo (aliases, softwares, arquivos .deb). |

> Novas categorias serão adicionadas conforme forem surgindo (ex.: `git/`, `docker/`, `windows/`, `utils/`).

## Como usar

Cada script é independente. Entre na categoria desejada, leia o README da pasta e execute
o script conforme as instruções. Em geral (Linux):

```bash
chmod +x nome-do-script
./nome-do-script
```

## Convenções

- Um diretório por categoria, em `kebab-case`.
- Cada categoria tem seu próprio `README.md` documentando os scripts.
- Scripts devem ser idempotentes sempre que possível (rodar duas vezes não quebra nada).
