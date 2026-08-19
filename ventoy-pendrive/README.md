# ventoy-pendrive

Scripts para o pendrive multiboot (32GB, formatado com [Ventoy](https://www.ventoy.net/)) —
Debian, Arch, Ubuntu, Windows e outras ISOs no mesmo pendrive, sem precisar regravar nada a
cada troca de distro.

## Scripts

### `sync-isos`
Copia as ISOs de `~/Downloads` (ou de outra pasta passada como argumento) pra dentro do
pendrive Ventoy. Idempotente — roda de novo sempre que baixar uma ISO nova, só copia o que
ainda não existe lá dentro. Usa `cp` puro (sem depender de `rsync`, que não vem instalado
por padrão no Debian).

Acha a partição sozinho pelo label `Ventoy` (`lsblk`/`findmnt`) e monta automaticamente via
`udisksctl` se ainda não estiver montada — não precisa de sudo, a partição de dados do
Ventoy é FAT32/exFAT normal.

## Como usar

```bash
chmod +x sync-isos
./sync-isos                  # usa ~/Downloads
./sync-isos ~/outra-pasta    # usa outra pasta como origem
```

### `ventoy-1.1.17/`
Cópia do Ventoy oficial (baixado de github.com/ventoy/Ventoy, checksum SHA-256 conferido).
Pra gravar o pendrive pela primeira vez (ou converter outro):

```bash
sudo bash ventoy-1.1.17/Ventoy2Disk.sh -i /dev/sdX
```

Troca `/dev/sdX` pelo dispositivo certo — confere antes com `lsblk -o NAME,SIZE,TRAN,MODEL`.
**Isso apaga tudo que tiver no pendrive.** Precisa rodar num terminal de verdade (sudo pede
senha interativa).

## Instalação 100% automática do Debian (`ventoy.json` + `preseed-debian-headless.cfg`)

Pro laptop de tela quebrada, sem monitor externo nenhum: instala Debian 13 sozinho, sem
nenhuma pergunta, e sobe com SSH por chave pública pronto (senha desabilitada no sshd).
Usuário `lucas`, hostname `beacon-node`.

**⚠️ Risco importante**: com `VTOY_DEFAULT_IMAGE` configurado, esse pendrive passa a
**auto-instalar Debian em qualquer PC** que bootar dele e ficar 15s sem apertar nenhuma
tecla — inclusive o seu PC principal, se você usar esse mesmo pendrive pra testar
Arch/COSMIC como planejado. Só usa esse pendrive assim configurado na hora de instalar o
laptop; depois que a instalação terminar, **apaga ou renomeia o `ventoy.json`** (ou pelo
menos a seção `control`) pra voltar ao comportamento normal (menu, sem timeout).

### Deploy (depois de rodar o `Ventoy2Disk.sh` no pendrive)

```bash
cp ventoy.json /caminho/do/ventoy/ventoy.json
mkdir -p /caminho/do/ventoy/ventoy
cp preseed-debian-headless.cfg /caminho/do/ventoy/ventoy/preseed-debian-headless.cfg
./sync-isos   # garante que o debian-13.6.0-amd64-netinst.iso está lá
```

### O que o preseed faz

- Localização pt_BR, teclado `br`, fuso `America/Sao_Paulo`.
- Rede via DHCP, hostname `beacon-node` (acessível como `beacon-node.local` via
  avahi-daemon, sem precisar achar o IP no roteador).
- Disco: detecta o primeiro disco disponível na hora (`list-devices disk`), não crava
  `/dev/sda` — funciona em qualquer nome de disco (SATA, NVMe, eMMC).
- Partição: LVM automático, recipe `atomic` (tudo numa partição só).
- Conta `lucas` com senha aleatória forte (hash sha512crypt no arquivo, nunca em texto
  puro) — serve de rede de segurança pro `sudo`, não é o método de acesso principal.
- Chave SSH pública instalada em `~/.ssh/authorized_keys`; login por senha desabilitado
  no sshd depois (`PasswordAuthentication no`, `PermitRootLogin no`).
- Pacotes: `sudo`, `openssh-server`, `avahi-daemon`, `curl`, mais o básico do `tasksel`.

### Depois de instalar

```bash
ssh -i ~/.ssh/beacon_node_ed25519 lucas@beacon-node.local
```

A chave privada (`~/.ssh/beacon_node_ed25519`) fica só na sua máquina principal — nunca
foi copiada pro pendrive nem pro laptop (só a `.pub` foi, via preseed).
