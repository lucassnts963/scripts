# gnome-session

GNOME instalado como opção "sob demanda", mantendo o boot pela TTY (sem display manager
autostartando) — o mesmo espírito do `start-hyprland`, só que pro GNOME.

## Scripts

### `install-gnome`
Instala `gnome-core` + `libnotify-bin`. O `gdm3` vem junto (é dependência obrigatória do
`gnome-core`, apt não deixa evitar), mas o script desativa e **mascara** o serviço logo
em seguida — ele fica instalado no disco, mas nunca sobe sozinho no boot.

### `gnome-toggle`
Liga ou desliga a sessão, dependendo se já tem uma rodando:
- **Sem sessão**: abre uma (`dbus-run-session -- gnome-session`), toma a TTY até você sair.
  Sobe o `watch-beacon-node` junto, e encerra ele automaticamente quando a sessão GNOME
  fecha — não fica processo perdido rodando.
- **Com sessão já aberta** (chamando de outra TTY/SSH): encerra ela.

### `watch-beacon-node`
Não roda sozinho — é chamado pelo `gnome-toggle`. Fica checando a cada 20s se o
`beacon-node` (laptop headless, ver `../ventoy-pendrive/`) já responde por SSH, manda uma
notificação assim que aparecer, e sai sozinho depois do primeiro sucesso (não vira
monitoramento permanente).

## Como usar

```bash
chmod +x install-gnome gnome-toggle watch-beacon-node
./install-gnome      # uma vez só
gnome-toggle          # abre a sessão; chama de novo (de outro terminal) pra fechar
```

Pra rodar de qualquer lugar sem o caminho completo, os três também ficam copiados em
`~/.local/bin` (já no PATH).
