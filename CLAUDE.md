# Notas para agentes de IA

Contexto rápido para quem for mexer neste repositório sem tê-lo lido inteiro.

## O que é

Sistema de boot em rede da Maratona SBC de Programação. Máquinas de
laboratório ligam por um pendrive, baixam o sistema operacional do servidor
em camadas squashfs e montam tudo com overlayfs. Durante a prova, o servidor
recebe telemetria e envia comandos (bloquear tela, limpar home, reiniciar).

Três partes: **servidor** (FastAPI, `server/`), **cliente de boot**
(initramfs + shell, `client/`) e **telas web** (JavaScript puro, `web/`).

## Invariantes — quebrar qualquer uma destas causa dano real

1. **Escrita atômica sempre.** Todo acesso ao disco passa por
   `server/app/fsdb.py` (tmp + `os.replace` + `flock`). Nunca escreva direto
   com `open(..., "w")` no diretório `data/`.

2. **O servidor roda com UM único worker uvicorn.** `services/notify.py`
   guarda os sinais de long-poll e SSE em memória do processo. Com dois
   workers, metade dos comandos demoraria os 5 s do mecanismo de segurança em
   vez de chegar na hora, e metade dos painéis não receberia eventos.

3. **`/boot/v3/*` responde texto puro.** Quem consome é shell dentro do
   initramfs, sem `jq`. Não converta essas rotas para JSON.

4. **Camadas extras vêm ANTES no manifest.** A ordem das linhas é a ordem do
   `lowerdir` do overlayfs, e a primeira ganha. Inverter faz a imagem base
   sobrescrever silenciosamente as personalizações.

5. **Nada de `read` interativo no caminho de boot.** Máquina de prova boota
   sozinha; um prompt esperando ENTER trava a sala inteira. Há um teste que
   falha se aparecer (`tests/test_bootstrap_shell.py`).

6. **Certificado sempre verificado.** Nada de `--check-certificate=false`. A
   única exceção é `GET /boot/v3/time`, que existe justamente para acertar o
   relógio e tornar a validação possível. Também há teste para isso.

7. **A rede pertence ao bootstrap do initrd.** O `stuff` servido não pode
   redefinir `configure_localnetwork`/`configure_wifi` — foi exatamente essa
   sobreposição que deixou o wifi morto na versão anterior. Há teste.

8. **Toda string de interface nasce nos três idiomas** (pt, en, es), em
   `web/common/locales/`. Teste compara as chaves dos três arquivos.

9. **O pendrive é liberado cedo.** O initrd copia a configuração para a RAM e
   desmonta antes de qualquer coisa de rede, avisando na tela. Não adicione
   leituras do pendrive depois desse ponto.

10. **`/api/v1/images/...` continua respondendo, para sempre.** O agente de
    telemetria (`client/telemetry/usr/share/mlog/agent.sh`) monta
    `"$NB_SERVER/api/v1/images/$IMAGEROOT"` e esse arquivo vai DENTRO da camada
    squashfs publicada: máquinas já instaladas chamam o caminho antigo, e não
    há como atualizá-las remotamente sem telemetria — que é justamente o que
    quebraria. O alias vive em `LegacyImagePathMiddleware`
    (`server/app/main.py`) e há teste-guarda em `tests/test_legacy_paths.py`.
    O mesmo vale para o contrato de boot (`/boot/v3/*`, `IMAGEROOT`,
    `nutellaboot.conf`, `NB_*`) e para os links já distribuídos
    (`/configureitor/?id=&tk=`).

11. **O que é de outro dono responde 404, não 403 — e sem credencial é 401,
    exista o objeto ou não.** Vale para todo o console
    (`services/ownership.py`) **e** para `auth.require_image_access`, que
    devolvia 403 e conferia a existência antes da credencial: eram dois
    oráculos de nomes de sala em ~26 rotas (config, machines, roster, alerts,
    layers). Chave de serviço é a exceção: quem a emite é a administração,
    então 403 de escopo/glob ali é o erro útil. Há teste
    (`tests/test_subadmin.py`).

12. **As mensagens do caminho de boot são em inglês, e saem pelo
    `client/stuff/05-ui.sh`.** É a única parte do sistema que não é traduzida
    em tempo de execução: quando a mensagem aparece, muitas vezes não há rede
    nem disco para carregar dicionário. As letras grandes são **espaços em
    fundo colorido**, não caracteres de desenho — no console do initrd não há
    `tput`, terminfo nem garantia de fonte. Uma tela fatal cabe em 25 linhas
    (VGA texto) e limpa o console antes de desenhar; passar disso rola o
    banner para fora. Há teste medindo altura e rejeitando acento em texto de
    tela. O `LANGUAGE` do formulário continua valendo para a tela de bloqueio
    e o agente.

13. **A camada base é a última da lista e é marcada com `role: base`.** Trocar
    a base entre temporadas usa `replace_role`, nunca o nome do arquivo — o
    nome muda todo ano (`icpc-latam2025` → `maratonalinux2026`) e casar por
    nome deixa as DUAS no modelo: a máquina baixa as duas raízes e as monta
    sobrepostas, sem erro no registro, no manifest nem no boot. Papéis:
    `base`, `telemetry`, `wifi`, `extra`. **Camada sem papel é o mesmo bug
    por outra porta**: `replace_role` não a reconhece, a antiga fica, e a
    trava que conta bases acha 1 porque a órfã nem entra na conta. Ferramenta
    que grava camada em disco marca o papel (`services/layer_roles.py`), e
    `nb3-nova-temporada`/`nb3-gerar-squash --register` recusam modelo com
    camada sem papel. Há teste (`tests/test_layer_roles.py`,
    `tests/test_nova_temporada.py`).

14. **O navegador não guarda credencial; o cookie de sessão só vale com o
    cabeçalho `X-NB-Console`.** A chave é trocada uma vez em
    `POST /api/v1/session` e vira cookie `HttpOnly`. O cabeçalho é o que
    impede CSRF nas 46 rotas de escrita — um `<form>` de outro site manda o
    cookie, mas não define cabeçalho. **Bearer continua sendo o caminho das
    ferramentas e do MOJ** e não pode quebrar. Não volte a escrever a
    credencial em `sessionStorage`/`localStorage`: foi essa ida e volta que
    fazia o console deslogar a cada reload (a tela regravava o campo de login
    vazio por cima da chave). **Rota que não usa `Depends` chama
    `auth.principal`** — nunca lê `Authorization` na mão: as duas rotas de
    layerbuild por imagem faziam isso e ficaram 401 para o console inteiro
    quando a sessão entrou, sem nenhum teste notar (todos usavam Bearer). As
    exceções são `GET` puro que um `<img>`/`EventSource` precisa carregar
    (SSE e prévia do wallpaper), que aceitam `?tk=` ou o cookie sem o
    cabeçalho. Há teste (`tests/test_session.py`,
    `tests/test_layer_builds_console.py`).

15. **Ferramenta que fala com a API tem que falhar alto.** O
    `nb3-gerar-squash` usava `curl -sS` sem `--fail`: um 404 (nome de modelo
    errado) devolvia o JSON de erro com código de saída **zero**, e o script
    terminava dizendo que registrou. Dois modelos ficaram vazios assim. Use
    `--fail-with-body` no shell, ou o helper `api()` em Python. O mesmo
    regrediu no `nb3-pack-upper --attach`; `publish.publish_file()` também
    nunca levanta exceção (falha vira `status: failed`), então quem publica
    confere o status. Há teste de texto nas duas coisas
    (`tests/test_nova_temporada.py`).

16. **Em `05-ui.sh`, cada temporário pertence a uma função só** (prefixo
    `_nbu_`). Não existe `local` em sh POSIX: `nb_banner` usava a mesma
    variável de laço que `nb_fatal_screen` usava para o tempo de espera, e o
    resultado era `sleep RAM` — a tela sumia antes de alguém ler. Há teste.

17. **O alerta de dispositivo fica até alguém dispensar.** Não some quando o
    pendrive é removido, e a chave de máquina **não** dispensa alerta —
    adulterar o agente não pode apagar o rastro. Está em
    `services/alerts.py`, com teste.

18. **O código de convite nunca é gravado dentro da site-image.** Ele é a
    credencial do console de sub-admin; se ficasse no `image.json`, quem
    tivesse só o token da imagem escalaria para sub-admin. O que fica gravado
    é `owner` (`"admin"` ou `"invite:<CÓDIGO>"`). Há teste.

19. **O boot REGRAVA o pendrive da sede quando ele está para trás**, e por isso
    `client/stuff/25-usbupdate.sh` é o arquivo mais perigoso do projeto: errar
    ali não dá tela feia, dá pendrive que não liga mais no meio de uma prova.
    A ordem não é negociável — baixar para o disco local, **conferir o md5**, e
    só então tocar na partição (não cabem os dois pares: ~399 MB para 202 MB de
    conteúdo, então os antigos saem antes). `nutellaboot.conf` e `wifi.conf`
    são da sede e não se toca. Falha de REDE não conta como tentativa (nada foi
    tocado, e blip de rede não pode condenar máquina); falha de ESCRITA conta, e
    o marcador em `$STORAGEDIR/.usbupd-tried` é o que impede um pendrive
    protegido contra escrita de reiniciar a máquina para sempre. A identidade
    vem de `tools/nb3-build-initrd`, que carimba `/etc/nutellaboot-build`
    dentro do initrd e o md5 em `client/build/build.json` — o md5 sai da
    ferramenta porque o servidor tem um worker só. Initrd sem carimbo não
    confere nada. Há teste com pendrive de mentira em disco
    (`tests/test_usb_update.py`).

20. **A produção não recebe edição manual.** Conserto se faz aqui, entra no
    repositório, e chega lá por `git pull` + o que o deploy manda instalar. Foi
    quebrada uma vez, com um `sed -i` no snippet do nginx direto no servidor: a
    máquina passou a ser diferente do repositório sem nada registrando a
    diferença, e o próximo reinstall apagaria a correção em silêncio. Por isso
    tudo que a produção precisa é ARQUIVO versionado (`deploy/`, `systemd/`) e
    não instrução em comentário. O procedimento está em `docs/operations.md`.

## Nomenclatura

- **modelo** (`model`, `data/models/<n>/model.json`): o que se configura uma
  vez — camadas (telemetria, wifi, pacotes) e o formulário (`schema.json` com
  os cadeados por campo). Criável pela API/tela; `from`/`duplicate` copia
  camadas e formulário.
- **site-image** (`data/site-images/<id>/`): a imagem derivada de um modelo,
  uma por sala/sede, com token, chaves e configuração próprias.
- **sub-admin** (`data/owners/<slug>.json`): quem entrou por convite. O
  próprio código é a credencial de console; o registro de identidade é
  separado do convite justamente para que revogar não deixe objetos órfãos.

O nome antigo era *template*/*image*; a migração está em
`tools/nb3-migrate-names` (idempotente, com `--dry-run`).

- **camada de telemetria**: `client/telemetry/` (agente, tela de bloqueio,
  regra de udev) empacotado por `tools/nb3-camada-telemetria`, que também
  publica e registra no modelo — removendo a anterior, senão duas versões do
  agente disputam o mesmo caminho e a primeira da lista vence em silêncio.

## Credenciais

| Prefixo | Quem usa | Onde fica |
|---|---|---|
| `nb3a_` | administração | hash em `data/keys/admin.json` |
| cookie `nb3_session` | console no navegador | `data/sessions.json` (0600, 30 dias) |
| `NB3-…` | sub-admin (o próprio convite) | claro em `data/invites.json` |
| `nb3s_` | serviços externos (MOJ), com escopos | hash em `data/keys/services.json` |
| `nb3i_` | dono da imagem (configureitor, hotconfig) | `data/site-images/<id>/token` |
| `nb3m_` | máquina (telemetria, fila de comandos) | `data/site-images/<id>/machine.key` |
| `nb3b_` | pendrive (endpoints de boot) | `data/site-images/<id>/boot.key` |

`auth.require_console` aceita admin **ou** sub-admin; `auth.require_admin` só
o primeiro. Rota nova de console usa `require_console` + as funções de
`services/ownership.py` — não escreva a checagem de dono à mão.

## Comandos

```bash
tools/nb3-init                     # instalação nova: emite e IMPRIME a chave
tools/nb3-dev                      # servidor em 127.0.0.1:8890
.venv/bin/python -m pytest -q      # 520 testes, ~42 s
tools/nb3-seed-testdata            # dados de teste (não é instalação)
tools/nb3-layer-worker --check     # confere as ferramentas rootless
```

O ambiente de teste tem um nginx externo que faz proxy de
`https://nutellaboot.charge.naquadah.com.br:8443` para `localhost:8890`.

## Armadilhas já encontradas (não repita)

- `httpx.ASGITransport` **não faz streaming**: executa a aplicação até o fim
  antes de devolver. Testes de SSE precisam de um uvicorn de verdade — veja
  `tests/test_live_server.py`.
- `asyncio.Event` guardado entre requisições quebra quando o loop muda. Os
  eventos são criados dentro da requisição que espera (`notify.py`).
- Módulos ES (`import`) **não carregam por `file://`** (CORS). Os temas da
  tela de bloqueio usam script clássico (`window.NB3Lock`) de propósito.
- `set prefix=($root)` numa imagem GRUB standalone quebra o carregamento de
  módulos (eles vivem no memdisk) e o menu abre vazio, sem erro visível.
- **`tools/nb3-dev` não recarrega sozinho.** Mudou código do servidor e foi
  testar com uma ferramenta de linha de comando? Reinicie (ou use
  `tools/nb3-dev --reload`). O sintoma engana: a suíte passa (importa o código
  do disco) e o comando real se comporta como a versão antiga — foi assim que
  um `replace_role` recém-escrito foi ignorado e um modelo ficou com duas
  bases.
- No builder de camadas, a poda e o `mksquashfs` precisam rodar **dentro** do
  mesmo namespace de usuário: os arquivos do apt pertencem a subuids e não
  dão nem para apagar de fora.
- **O initrd não tem `head`, e a falta dele não aparece.** `nb_conf_value`
  terminava em `| head -n1`: o pipe morria com "head: not found" e a função
  devolvia VAZIO para tudo que vem do pendrive — `IMAGEROOT`, `NB_BOOT_KEY`,
  `NB_SERVER`. O pendrive genérico caía na tela "NO IMAGE" com o arquivo
  preenchido, e o de sede ignorava o servidor configurado, indo para o padrão
  embutido. Só apareceu num boot de verdade em qemu. Comando externo no
  caminho de boot: confira se o hook o copia (`tests/test_bootstrap_shell.py`
  roda com um PATH mínimo).
- **`copy_exec ORIGEM DIRETÓRIO` grava COM O NOME DO DIRETÓRIO** quando o
  diretório ainda não existe no initrd em construção — o initramfs-tools só
  acrescenta o nome do arquivo se o destino já for um diretório lá dentro.
  `/usr/bin` existe, então funciona; `/usr/libexec/coreutils` não existia, e a
  `libstdbuf.so` virou o ARQUIVO `/usr/libexec/coreutils`. O `stdbuf` achou
  arquivo onde esperava diretório, saiu 125 **antes de executar o aria2c**, e
  nenhuma máquina baixou mais nada. Destino sempre com o caminho completo, e
  `mkdir -p "$DESTDIR/..."` antes. O `nb3-build-initrd` agora confere a lista
  do que entrou (`lsinitramfs`) e falha alto.
- **O awk do initrd é o do busybox, e o `printf "%d"` dele é de 32 bits.** A
  camada base tem 6,1 GiB: o total da barra saía `-2147483648`. Use `%.0f` para
  qualquer contagem de bytes. O awk de desenvolvimento é de 64 bits, então o
  teste passa — o guarda que vale é o estático
  (`tests/test_download_progress.py`). Aritmética do `ash` e `test -ge` são de
  64 bits, esses não truncam.
- **Nada do caminho de boot pode depender de enfeite.** A barra de progresso
  tinha poder de veto sobre o download: com `2>&1 | awk` filtrando só as linhas
  de progresso, todo diagnóstico do aria2 (TLS, 404, DNS) e o próprio erro do
  `stdbuf` iam para o lixo. Quem filtra repassa o que não casou para
  `/dev/stderr`, e quem usa ferramenta opcional sonda antes
  (`nb_progress_probe`) e degrada em vez de falhar.
- **`nb3-qemu-shot` com 2 GB não boota**: o kernel não descompacta um initrd de
  185 MB e a tela fica parada em "Booting", sem erro. Use `--mem 4G`.
- **`configure_networking` do initramfs-tools roda na NOSSA shell e deixa
  `IP="done"`.** Ele marca isso assim que existe um `/run/net-*.conf`, e a
  chamada seguinte cai em `case ${IP} in none|done|off)` e **não roda DHCP
  nenhum**. Chamá-lo duas vezes (cabo, depois wifi) é o padrão daqui, então
  `configure_localnetwork` guarda `IP`/`IP6` na entrada e restaura antes de
  cada chamada (`nb_net_reset`). Sem isso, basta o cabo pegar um lease que não
  alcança o servidor para o wifi ficar sem endereço para sempre, calado. O
  arquivo de verdade está DENTRO do initrd construído (`scripts/functions`) —
  para lê-lo, extraia o cpio: o initrd é uma concatenação de arquivos cpio, o
  último comprimido com zstd.
- **Wifi que associa e cai em 1 s é negociação de chave, não DHCP.**
  `deauthenticating ... by local choice` quer dizer que o CLIENTE desistiu:
  senha recusada, ou AP em WPA2/WPA3 misto exigindo PMF contra um bloco só com
  `key_mgmt=WPA-PSK`. O log do `wpa_supplicant` (`-f`) morre com o initrd, por
  isso `nb_wifi_report` o leva para a tela — sem a senha.

## Estilo

Código, comentários, mensagens e documentação em **português do Brasil**.
Comentário só quando explica uma restrição que o código não mostra (por que
algo é assim), nunca narrando o que a linha faz.
