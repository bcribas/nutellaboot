# O caminho do boot

Este documento descreve o que acontece entre ligar a máquina e ter o Maratona
Linux na tela. Vale para quem precisa entender uma falha na sala de prova e
para quem vai mexer no código do cliente.

## Visão geral

```
   ┌─────────────┐
   │  pendrive   │  partição única FAT32, label NB3CFG
   │  (NB3CFG)   │  /EFI/BOOT/BOOTX64.EFI  /vmlinuz  /initrd.img
   └──────┬──────┘  /grub.cfg  /nutellaboot.conf  /wifi.conf
          │
          ▼
   ┌─────────────┐  acha a partição pelo arquivo nutellaboot.conf
   │    GRUB     │  (não depende de número de disco) e carrega o
   │             │  grub.cfg editável da própria partição
   └──────┬──────┘
          │  linux /vmlinuz boot=nutellaboot ...
          ▼
   ┌─────────────┐
   │   kernel +  │  initramfs-tools chama o script `nutellaboot`
   │    initrd   │  porque a linha de comando tem boot=nutellaboot
   └──────┬──────┘
          │
          ▼
   ┌──────────────────────────────────────────────────────────┐
   │ BOOTSTRAP (client/initramfs-tools/scripts/nutellaboot)    │
   │                                                            │
   │  1. lê nutellaboot.conf e wifi.conf da partição NB3CFG,    │
   │     copia para a memória e desmonta: "PODE RETIRAR O       │
   │     PENDRIVE AGORA"                                        │
   │  2. sobe a rede: cabeada primeiro, wifi se preciso —       │
   │     ESPERANDO a associação de verdade                      │
   │  3. acerta o relógio (/boot/v3/time)                       │
   │  4. confere o servidor (/boot/v3/sanity → "penguin")       │
   │     com TLS validado                                       │
   │  5. baixa /boot/v3/<imagem>/stuff, autenticado com a       │
   │     chave de boot, e faz `.` nele                          │
   └──────┬───────────────────────────────────────────────────┘
          │  chama nb3_mountroot(), definido pelo stuff
          ▼
   ┌──────────────────────────────────────────────────────────┐
   │ STUFF v3 (montado pelo servidor a cada requisição)        │
   │                                                            │
   │  • checagens: virtualização, RAM mínima, factory reset     │
   │  • acha um disco local com espaço (cache e home)           │
   │  • baixa o manifest e as camadas .squash (md5 conferido)   │
   │  • monta tudo como overlayfs                               │
   │  • semeia a imagem para a rede local, se configurado       │
   │  • swap, home persistente                                  │
   │  • ~15 ajustes no sistema montado (firewall, teclado,      │
   │    fuso, autologin, wallpaper, perfis de wifi…)            │
   └──────┬───────────────────────────────────────────────────┘
          │
          ▼
   ┌─────────────┐  a rede volta para o NetworkManager;
   │   sistema   │  o agente sobe pelo rc.local e passa a
   │   pronto    │  escutar comandos do servidor
   └─────────────┘
```

## Configuração: quem manda em quem

A ordem de precedência é sempre a mesma:

| Prioridade | Origem | Como se escreve |
|---|---|---|
| 1 (maior) | Linha de comando do kernel | `IMAGEROOT=26brbr` no `grub.cfg` |
| 2 | `nutellaboot.conf` do pendrive | `IMAGEROOT=26brbr` |
| 3 (menor) | Padrão embutido no initrd | `/etc/nutellaboot.defaults` |

O arquivo `nutellaboot.conf` aceita:

```sh
# Qual imagem esta máquina deve bootar (obrigatório).
IMAGEROOT=26brbr

# Chave de boot da imagem: autoriza este pendrive a baixar o script de boot e
# a lista de camadas. Sem ela, o servidor recusa o download.
NB_BOOT_KEY=nb3b_...

# Servidor do NutellaBoot (opcional; use para apontar a um servidor de teste).
#NB_SERVER=https://nutellaboot.naquadah.com.br

# Fixa nomes no /etc/hosts do initrd: "nome ip", uma linha por entrada.
#NB_HOSTS=nutellaboot.charge.naquadah.com.br 10.0.2.2
```

### O pendrive sai cedo

Assim que o `nutellaboot.conf` e o `wifi.conf` são copiados para a memória, o
initrd desmonta a partição e mostra na tela, em três idiomas, que **o pendrive
já pode ser retirado**. Nada mais é lido dele durante o resto do boot. Numa
sala com 60 máquinas, isso libera o pendrive para a próxima máquina em
segundos, em vez de ficar preso até o sistema subir.

### Por que existe um pendrive genérico

No NutellaBoot 2, cada sede tinha a sua imagem de pendrive de 400 MB, e a
**única** diferença entre elas era o texto `IMAGEROOT=` na linha de comando do
GRUB. Eram ~45 imagens idênticas de 400 MB para trocar uma palavra.

Aqui a partição é FAT32 e monta em qualquer computador: Windows, macOS, Linux.
Trocar a sede de um pendrive é abrir o `nutellaboot.conf` no bloco de notas e
salvar. Grave a mesma imagem em todos os pendrives e edite um arquivo de texto
em cada um — ou grave já com `--imageroot`, se preferir fixar.

O `NB_HOSTS` merece atenção: ele escreve linhas no `/etc/hosts` do initrd. Isso
resolve o nome sem mexer em DNS **e sem abrir mão da validação do
certificado**, porque o nome continua sendo o mesmo — muda só o endereço. É o
que permite testar em máquina virtual (onde o hospedeiro é sempre `10.0.2.2`) e
apontar para um espelho local durante a prova.

## Wifi

O arquivo `wifi.conf`, na mesma partição, tem uma rede por linha com campos
separados por **TAB**:

```
ssid <TAB> senha <TAB> [hidden]
```

```
ICPC-BR	senha-da-rede-da-maratona
ICPC-BR-EMG
minha-rede-oculta	senha123	hidden
```

Rede aberta: deixe a senha vazia (dois TABs seguidos). Rede oculta: escreva
`hidden` no terceiro campo — vira `scan_ssid=1`, sem o qual a rede não é
encontrada.

Este arquivo alimenta **duas** coisas, a partir de uma fonte só:

1. o `wpa_supplicant.conf` que o initrd gera para conectar antes de baixar o
   sistema (`nb_write_wpaconf`);
2. os perfis `.nmconnection` do NetworkManager no sistema já montado
   (`nb3_post_nm_wifi`, módulo `80-nm-wifi.sh`).

No NutellaBoot 2 eram duas bases de credenciais mantidas à mão: o
`wpa_supplicant.conf` embutido no initrd e a camada `wifis.squash` com os
perfis do NetworkManager. Trocar a senha da rede exigia lembrar das duas — e
regravar o initrd.

### A espera de associação

`configure_wifi()` não dá um `sleep` e torce. Ele sobe o `wpa_supplicant` e
consulta o `wpa_cli` em laço até ver `wpa_state=COMPLETED`, com teto de 30
segundos (`NB_WIFI_TIMEOUT`). Só então o DHCP roda.

O NutellaBoot 2 dava um `sleep 3` cego — tempo insuficiente para o handshake
WPA2 seguido de DHCP. Mas o problema maior era outro: **o wifi nunca era
sequer tentado**. O initrd trazia `wpa_supplicant` e todo o firmware, e o
`stuff` servido pelo servidor sobrescrevia `configure_localnetwork()` sem
chamar `configure_wifi()`. A função existia e nunca era executada.

No v3 a rede pertence **exclusivamente ao bootstrap**. O `stuff` recebe a rede
pronta e não pode redefinir essas funções — há um teste automatizado
(`test_stuff_does_not_redefine_network_functions`) que falha se alguém
declarar `configure_localnetwork`, `configure_wifi` ou `nb_write_wpaconf`
dentro de `client/stuff/`.

A ordem prática de `configure_localnetwork()` é: tenta a rede cabeada, checa se
o servidor responde; se não, tenta o wifi e checa de novo. Até 10 rodadas
(`NB_NET_TRIES`); esgotadas, a máquina avisa e reinicia — nunca fica parada
esperando alguém.

## TLS: validação de verdade

O hook do initrd copia o **bundle completo de CAs do sistema** para dentro da
imagem (`/etc/ssl/certs/ca-certificates.crt`), e todo download de conteúdo
valida o certificado: `wget.good --ca-certificate=...` no bootstrap e
`aria2c --check-certificate=true --ca-certificate=...` no stuff.

O NutellaBoot 2 embutia um certificado só, dentro do próprio script, e depois
passava `--check-certificate=false` em **todos** os downloads — era impossível
saber se o sistema baixado vinha de onde deveria.

### O relógio vem antes do certificado

Certificado é validado contra a data do sistema. Máquina de laboratório com
bateria de RTC velha acorda em 1970 ou em 2035, e aí **qualquer** certificado
parece inválido. Por isso o passo 3 existe: `/boot/v3/time` devolve a hora do
servidor em texto puro, e é o **único** ponto que não valida certificado —
justamente porque existe para tornar a validação possível logo em seguida. O
ajuste só acontece se o desvio passar de 60 segundos.

Há um teste (`test_no_disabled_certificate_check`) que varre os scripts do
cliente e falha se aparecer `--check-certificate=false` ou
`--no-check-certificate` em qualquer lugar que não seja essa chamada de hora.

### A chave de boot

Os endpoints de boot não são abertos. Cada imagem tem uma chave própria
(`data/images/<id>/boot.key`, prefixo `nb3b_`), que vai no `nutellaboot.conf`
do pendrive e é enviada em toda requisição de `manifest`, `stuff`, `wallpaper`,
`lockinfo`, `lockstate` e registro de seeder. Sem ela, o servidor responde 401.

No NutellaBoot 2 bastava saber o nome da sede para baixar o script de boot
inteiro, com as senhas embutidas nele.

A chave chega ao servidor de três formas equivalentes, porque cada ferramenta
do cliente fala de um jeito:

| Forma | Quem usa |
|---|---|
| Corpo de POST (`key=…`) | `wget.good` no bootstrap e no `nb_get` do stuff |
| Cabeçalho `X-NB-Boot-Key` | `aria2c` (que faz GET) e a tela de bloqueio |
| Query string (`?key=…`) | conveniência para depuração com `curl` |

Para pegar a chave: `GET /api/v1/images/<imagem>/boot-key` (admin). Para
trocá-la: `POST /api/v1/images/<imagem>/boot-key/rotate` — mas atenção, todo
pendrive daquela imagem precisa ter o `nutellaboot.conf` atualizado depois,
senão para de bootar.

### Por que as camadas podem vir por HTTP

O manifest chega por HTTPS validado e traz o **md5 de cada camada**. As URLs
dentro dele apontam para os seeders da rede local (`http://<ip>/<arquivo>`,
servidos por `webfsd` na porta 80) e, por último, para o CDN.

Um seeder malicioso ou defeituoso não consegue entregar conteúdo alterado: o
`stuff` confere o md5 de cada arquivo baixado contra o valor que veio pelo
canal autenticado, e descarta o que não bater. HTTP na rede local é uma
otimização de transporte, não um buraco de confiança.

## O stuff v3

O `stuff` é o script que faz o trabalho pesado do boot. Ele **não** vive no
pendrive: é montado pelo servidor a cada requisição e baixado a cada boot.
Isso é o que permite corrigir o comportamento de todas as máquinas da maratona
sem regravar um único pendrive.

O servidor concatena, em ordem, os módulos de `client/stuff/`, precedidos das
variáveis de configuração daquela imagem:

| Módulo | O que faz |
|---|---|
| `00-header.sh` | `nb_log`, `nb_warn`, `nb_fatal`, `nb_retry` — a política de erro |
| `20-download.sh` | `nb_download` (multi-URL, TLS, retry), `nutella_md5sum`, `download_boot_files` |
| `30-storage.sh` | `nutella_findblock` (acha disco), checagem de virtualização e de RAM mínima |
| `40-mount.sh` | monta as camadas em overlayfs, home persistente, swap em disco e zram |
| `50-seed.sh` | semeia a imagem para a rede local, com heartbeat |
| `60-postmount.d/*` | os ajustes no sistema montado, um arquivo por assunto |
| `90-main.sh` | orquestra tudo (`nb3_mountroot`) e devolve a rede ao NetworkManager |

Os ajustes de `60-postmount.d/` são:

| Arquivo | Ajuste |
|---|---|
| `10-home.sh` | home do usuário `icpc`, marca de limpeza |
| `15-machineid.sh` | machine-id estável + id do boot atual |
| `20-secrets.sh` | escreve `/etc/.nb3` |
| `25-rclocal.sh` | `rc.local` e partida do agente |
| `30-firewall.sh` | firewall da maratona e serviços desligados |
| `35-limits.sh` | limites de processos, `dmesg` liberado |
| `40-locale.sh` | idioma do sistema |
| `45-timezone.sh` | fuso horário |
| `50-autologin.sh` | autologin no GDM |
| `55-dconf.sh` | teclados, página inicial do navegador |
| `60-polkit.sh` | permissões de USB, rede, sudo |
| `65-firefox.sh` | políticas do Firefox e navegador padrão |
| `70-wallpaper.sh` | papel de parede da sede |
| `75-clionkey.sh` | licença do CLion |
| `80-nm-wifi.sh` | perfis de wifi do NetworkManager |

### As três regras do stuff

**1. Nada de `read` interativo.** Máquina de prova boota sozinha, muitas vezes
com a sala vazia. Um `read -p "Continue anyway?"` no caminho de erro — como o
NutellaBoot 2 tinha no download do wallpaper — significa uma máquina parada
esperando alguém que não está lá. Erro grave usa `nb_fatal`, que mostra a
mensagem, espera 30 segundos e reinicia. Erro contornável usa `nb_warn` e
segue. Um teste (`test_no_interactive_read_in_client_scripts`) impede que isso
volte.

**2. Retry que funciona.** O `download_file` do nb2 só repetia quando o aria2
saía com código exatamente `1` — a maioria das falhas reais passava direto — e
ainda decidia sucesso ou fracasso pelo contador de tentativas, não pelo
resultado. O `nb_download` do v3 repete em qualquer código diferente de zero,
verifica que o arquivo não ficou vazio, e devolve o resultado real.

**3. Nada de `if` por sede.** O `stuff` do nb2 era compartilhado por 125
imagens e continha trechos do tipo `if [ "$IMAGEROOT" = "25unb-apc" ]`,
incluindo um hash de senha de root escrito no meio do arquivo. No v3 isso
virou variável de configuração: `NB_ICPC_SUDO`, `NB_ROOT_PW_HASH`,
`NB_ENABLE_QUERO_SER_SEDE`, `NB_HIDE_DOCS_APPS`.

## O que fica no sistema montado

O módulo `20-secrets.sh` escreve `/etc/.nb3` (modo 600). É o contrato entre o
boot e o sistema em execução:

```sh
NB_SERVER='https://nutellaboot.naquadah.com.br'
IMAGEROOT='26brbr'
NB_MACHINE_KEY='nb3m_...'
NB_BOOT_KEY='nb3b_...'
NB_LOCK_THEME='classico'
NB_LOCK_FALLBACK_HASH='<salt>$<sha256>'
NB_LANGUAGE='pt'
```

Quem lê esse arquivo:

- **`/usr/share/mlog/agent.sh`**, iniciado pelo `rc.local`. Roda dois laços: um
  de comandos, pendurado em long-poll de até 25 segundos, que volta no instante
  em que alguém manda algo pelo painel; e um de telemetria, que reporta o
  estado a cada ~45 segundos. Um terceiro laço, o `lock_watchdog`, garante que
  a tela de bloqueio volte em até 3 segundos se alguém matar o processo.
- **`/usr/bin/maratona-wait`**, a tela de bloqueio. Lê o tema, o idioma e o
  hash da senha de emergência daqui. No nb2, esses valores eram corrigidos em
  tempo de execução com um `sed -i 16d` — apagar a linha 16 do arquivo, por
  número.

No fim do boot, `fixnetworktoreconnect()` devolve a rede ao NetworkManager do
sistema: limpa os endereços do initrd, desliga o `systemd-networkd` e encerra o
`wpa_supplicant` do initramfs. Daí em diante quem manda na rede é o sistema
normal, usando os perfis gerados a partir do mesmo `wifi.conf`.
