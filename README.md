# scripts

Coleção de scripts úteis que uso no dia a dia para automatizar e facilitar meu trabalho.
Organizados por categoria — cada pasta agrupa scripts de um mesmo tema e traz um README
explicando o que cada um faz e como usar.

## Categorias

| Categoria | Descrição |
|-----------|-----------|
| [`organize-downloads/`](./organize-downloads) | Script Node que organiza a pasta de Downloads movendo os arquivos para subpastas por tipo. |
| [`ubuntu-setup/`](./ubuntu-setup) | Scripts de pós-instalação e configuração de um Ubuntu novo (aliases, softwares, arquivos .deb). |
| [`ventoy-pendrive/`](./ventoy-pendrive) | Sincroniza ISOs de `~/Downloads` pro pendrive multiboot Ventoy. |
| [`gnome-session/`](./gnome-session) | Instala e liga/desliga uma sessão GNOME sob demanda a partir da TTY, sem display manager. |
| [`debian-headless-usb/`](./debian-headless-usb) | Remasteriza o netinst do Debian pra instalar sem tela (disco, rede, SSH). Sem Ventoy — pendrive dedicado. |
| [`montisol/`](./montisol) | Backup diário em CSV da base de medição do Trocador (SQLite) em projects/montisol/assets/medicao/backup/AAAA-MM-DD/, guardando 60 dias |
| [`agentes-freio/`](./agentes-freio) | Freio de mão: /pausar <id> cria agentes/<id>/PAUSADO no vault com data e quem pediu |

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
