# ubuntu-setup

Scripts de pós-instalação e configuração de um Ubuntu recém-instalado — as coisas que
sempre faço logo depois de instalar o sistema.

## Scripts

### `getting-started`
Script principal de configuração inicial.

**Aliases criados:**

```bash
alias c='clear'
alias update='sudo apt update'
alias upgrade='sudo apt upgrade -y'
alias up='update && upgrade'
alias install='sudo apt install'
alias src='source .bashrc'
```

**Softwares instalados:**
- git
- wget
- ca-certificates
- curl
- gnupg
- lsb-release
- openssh-client
- openssh-server
- openjdk-18-jdk
- docker engine
- docker compose
- nvm

### `install-deb-files`
Instala arquivos `.deb` em lote. Antes de rodar, crie uma pasta chamada `deb-files`
dentro de `Downloads` e coloque nela todos os `.deb` que deseja instalar.

### `post-installation`
Passos adicionais de pós-instalação.

## Como usar

```bash
chmod +x getting-started
./getting-started
```
