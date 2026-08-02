# Arquitetura do NutellaBoot 3

Este documento explica como o sistema é organizado, onde cada dado mora e
quais regras precisam ser respeitadas por quem for mexer no código. Se você
quer apenas *usar* a API, vá direto para [api.md](api.md).

## Visão geral

O NutellaBoot é uma ferramenta de gestão de laboratórios com boot em rede: a
máquina dá boot por um pendrive minúsculo, baixa um sistema Linux do servidor
(ou de um colega na rede local), monta tudo como um sistema de arquivos em
camadas e entrega o desktop pronto. Serve para provas, laboratórios de ensino e
salas gerenciadas; a Maratona SBC de Programação é o uso de origem e aparece
como exemplo ao longo do texto. Durante uma sessão, o mesmo servidor recebe
telemetria das máquinas e envia comandos para elas — inclusive o bloqueio de
tela.

As imagens são criadas pela administração ou, com um **código de convite**, por
pessoas de fora, que assim montam a própria imagem sem depender de aprovação a
cada vez (ver a seção de autorização).

São três camadas:

| Camada | Onde vive | O que faz |
|---|---|---|
| **Servidor** | `server/app/` (FastAPI + uvicorn) | API REST, montagem do script de boot, fila de comandos, telemetria, eventos |
| **Cliente de boot** | `client/` | initramfs (bootstrap), `stuff` (script de boot modular), agente de telemetria, tela de bloqueio |
| **Interfaces web** | `web/` (JavaScript puro) | configureitor, painel do laboratório (hotconfig), administração, prévia dos temas de bloqueio |

### Fluxo de um boot

```
   ┌────────────────────────────────────────────────────────────────┐
   │ PENDRIVE (partição FAT "NB3CFG", editável em qualquer sistema) │
   │   grub.cfg · vmlinuz · initrd.img                              │
   │   nutellaboot.conf  (IMAGEROOT, NB_BOOT_KEY, NB_SERVER, HOSTS) │
   │   wifi.conf         (ssid <TAB> senha [<TAB> hidden])          │
   └───────────────────────────┬────────────────────────────────────┘
                               │  GRUB carrega kernel + initrd
                               ▼
   ┌────────────────────────────────────────────────────────────────┐
   │ INITRD — client/initramfs-tools/scripts/nutellaboot            │
   │  1. lê a configuração do pendrive (cmdline > pendrive > padrão)│
   │     e desmonta a partição: o pendrive já pode ser retirado     │
   │  2. fixa NB_HOSTS no /etc/hosts                                │
   │  3. sobe a REDE, wifi inclusive, e ESPERA a associação         │
   │  4. acerta o relógio      → GET /boot/v3/time                  │
   │  5. testa o servidor      → GET /boot/v3/sanity  (TLS estrito) │
   │  6. baixa e executa       → POST /boot/v3/{img}/stuff  + chave │
   └───────────────────────────┬────────────────────────────────────┘
                               │  o stuff assume daqui
                               ▼
   ┌────────────────────────────────────────────────────────────────┐
   │ STUFF — client/stuff/*.sh (montado pelo servidor a cada boot)  │
   │  · acha um disco local com espaço  (≥ ~14 GB)                  │
   │  · GET /boot/v3/{img}/manifest → "MD5 ARQUIVO URL1 URL2 …"     │
   │  · baixa cada camada com aria2c (todas as URLs como espelhos)  │
   │  · confere o md5 e monta overlayfs: extras primeiro, base ao fim│
   │  · aplica a configuração (60-postmount.d/), grava /etc/.nb3    │
   └───────────────────────────┬────────────────────────────────────┘
                               │  entrega o controle ao sistema
                               ▼
   ┌────────────────────────────────────────────────────────────────┐
   │ SISTEMA EM EXECUÇÃO                                            │
   │  agente (agent.sh):  long-poll de comandos + telemetria        │
   │  tela de bloqueio (maratona-wait): tema local, senha reserva   │
   │  seeder opcional: serve o cache para as outras máquinas da sala│
   └────────────────────────────────────────────────────────────────┘
```

## O banco-filesystem

Não há banco de dados. O estado é um diretório, `data/`, e cada arquivo tem
dono e propósito claros. Isso mantém a inspeção e o socorro manual possíveis
no meio de uma prova — abrir o arquivo e olhar sempre funciona.

```
data/
├── server.json                  configuração global do servidor
├── invites.json                 {"NB3-XXXX-XXXX": {max_images, used_images, build_quota, template, expires_at, note}}
├── requests/<id>.json           pedidos de imagem (wanted_name, contact, note, status)
├── keys/
│   ├── admin.json               {"keys":[{"id","sha256"}]}  — só hashes
│   └── services.json            {"<nome>": {"sha256","scopes","images"}}
├── templates/<nome>/
│   ├── template.json            {"layers":[…], "public": bool, "description"}
│   └── schema.json              formulário de configuração (rótulos pt/en/es) + `locked` por campo
├── images/<id>/
│   ├── image.json               id, fullname, template, namespace, unlocked, wallpaper_locked; nas de auto-atendimento também self_service e build_quota
│   ├── token                    nb3i_… — credencial do configureitor (0600)
│   ├── machine.key              nb3m_… — credencial das máquinas (0600)
│   ├── boot.key                 nb3b_… — credencial do pendrive (0600)
│   ├── config.json              {"values": {...}} — o que a sede escolheu
│   ├── layers-extra.json        camadas extras desta imagem (prioridade alta)
│   ├── wallpaper.png            arquivo enviado pelo configureitor
│   ├── wallpaper.json           {md5, size, filename, content_type}
│   ├── seeders.json             {"<ip>": {"last_seen": epoch}}
│   ├── roster.json              times/usuários (nome, organização, país, lugar)
│   ├── roster/logos/<org>.svg   logotipos das instituições (svg ou png)
│   ├── webhooks.json            destinos de eventos (0600, guarda o segredo)
│   └── machines/<mac>/
│       ├── machine.json         mac, first_seen, last_seen
│       ├── status.json          última telemetria recebida
│       ├── binding.json         vínculo com o roster (user_id, seat)
│       ├── lockstate.json       {locked, since, by}
│       ├── queue/<ts>-<cid>.json  comandos pendentes (um arquivo cada)
│       └── acks.log             confirmações, JSONL com teto de tamanho
├── layerbuilds/
│   ├── queue/<job>.json         pedidos de construção de camada
│   ├── running/<job>.json+log   em andamento
│   ├── done/<job>.json+log      concluídos (com `output`: file, md5, size)
│   └── failed/<job>.json+log    falhas (com `error`)
├── publish/<arquivo>.json       envio ao servidor de arquivos: {file, kind, status, url, error}
├── usb/                         imagens de pendrive geradas com --publish
└── blobs/                       squashfs construídos aqui, servidos em /blobs/
```

O `server.json` guarda, além da URL base e do TTL dos seeders, o bloco de
publicação — é o único lugar que sabe o nome do servidor de arquivos, o que
permite trocá-lo por uma CDN sem mexer em código:

```json
"publish": {
  "enabled": true,
  "host": "files.mdp.naquadah.com.br",
  "user": "root",
  "paths":     {"layers": "/var/www/html/maratonalinux", "usb": "/var/www/html/mlbootimages"},
  "base_urls": {"layers": "https://files.mdp.naquadah.com.br/maratonalinux",
                "usb":    "https://files.mdp.naquadah.com.br/mlbootimages"}
}
```

Camadas e imagens de pendrive são enviadas por `rsync` sobre SSH e passam a ser
baixadas de lá; o estado de cada envio fica em `publish/`, que é o que alimenta
o botão de reenviar quando o servidor está fora do ar. Falha de publicação não
quebra o boot: a camada continua sendo servida pela máquina de gestão.

O MAC é normalizado para minúsculas com hífen (`52-54-00-12-34-56`), que é o
formato entregue pelo `BOOTIF` na linha de comando do kernel.

## Invariantes

Estas cinco regras não são estilo: quebrar qualquer uma delas causa falha
real, geralmente no pior momento.

**1. Toda escrita é atômica e serializada.** `fsdb.py` grava em arquivo
temporário no mesmo diretório, faz `os.fsync` e só então `os.replace`. Toda
mutação que dependa de leitura anterior acontece dentro de `fsdb.locked(dir)`,
que é um `flock` exclusivo em `<dir>/.lock`. Leitura nunca precisa de trava,
porque `os.replace` é atômico: ou se vê o conteúdo antigo, ou o novo, nunca um
arquivo pela metade. Centenas de máquinas gravando telemetria ao mesmo tempo
não podem corromper nada.

**2. O servidor roda com UM único worker uvicorn.** `notify.py` mantém em
memória os sinais que acordam o long-poll dos agentes e as filas dos clientes
SSE. Com mais de um worker, um comando enfileirado no processo A não acordaria
o agente pendurado no processo B — ele só seria entregue na reconferência
seguinte, e o ganho de latência evaporaria. O estado real está sempre no
disco; a memória guarda apenas os sinais. Nunca use `--workers` maior que 1.

**3. Os endpoints `/boot/v3` são texto puro.** Quem os consome é o shell do
initramfs, que tem `busybox`, `wget` e `aria2c`, mas não tem `jq`. O manifest
é lido com um `while read MD5 ARQUIVO URLS`. Se algum dia esses endpoints
virarem JSON, o boot para de funcionar em toda máquina já gravada.

**4. Camadas extras vêm antes no manifest.** A ordem das linhas é a ordem dos
`lowerdir` do overlayfs, e no overlayfs quem vem primeiro tem prioridade. É
assim que uma camada extra sobrepõe um arquivo da imagem base. `store.image_layers()`
concatena `layers-extra.json` **antes** das camadas do template — inverter
isso faz a camada extra ser silenciosamente ignorada.

**5. Toda string de interface nasce nos três idiomas.** As telas funcionam em
português, inglês e espanhol. Os dicionários ficam em `web/common/locales/{pt,en,es}.json`
e os rótulos do formulário de configuração ficam no próprio `schema.json`, com
as três traduções. Há teste automatizado comparando as chaves dos três
arquivos: uma string a menos em espanhol quebra a suíte.

### Onde ficam as travas

A trava **por campo** vive no `schema.json` do template (a chave `locked` de
cada campo) e vale para todas as imagens Oficiais daquele template; ela é
editável pela tela do `/admin/` ou por `PUT /api/v1/templates/{nome}/schema/locks`,
que só altera essa chave e preserva o resto do formulário. Já a trava do
**papel de parede** é por imagem, no `wallpaper_locked` do `image.json`, e é
verificada na rota de upload. As duas seguem a mesma regra: administração
sempre pode; imagens marcadas `unlocked` (perfil Livre) ignoram as travas de
campo.

## Autenticação

Cinco classes de credencial, distinguidas pelo prefixo. As chaves de
administração e de serviço ficam em disco apenas como hash SHA-256; `token`,
`machine.key` e `boot.key` são segredos distribuídos (para a sede, para as
máquinas e para o pendrive), e por isso ficam em arquivos com modo `0600`.
Toda comparação usa `secrets.compare_digest`.

| Classe | Prefixo | Como é enviada | O que pode |
|---|---|---|---|
| Administração | `nb3a_` | `Authorization: Bearer` | tudo: criar/apagar imagens, templates, camadas, webhooks, chaves de serviço |
| Serviço (MOJ) | `nb3s_` | `Authorization: Bearer` | só o que os escopos permitirem, e só nas imagens que o filtro de globs permitir |
| Imagem | `nb3i_` | `Authorization: Bearer` | configurar a própria imagem, ver e comandar as máquinas dela |
| Máquina | `nb3m_` | cabeçalho `X-NB-Machine-Key` | enviar telemetria, buscar comandos pelo long-poll, confirmar execução |
| Boot | `nb3b_` | POST `key=`, cabeçalho `X-NB-Boot-Key` ou `?key=` | baixar manifest, script de boot, wallpaper e dados da tela de bloqueio; entrar no pool de seeders |

Escopos disponíveis para chaves de serviço: `machines:read`, `commands:write`,
`bindings:write`, `roster:read`, `roster:write`, `config:write`. O campo
`images` aceita globs (`["26*"]` libera só as sedes de 2026); vazio significa
todas.

O token de imagem só é reconhecido no contexto da própria imagem — apresentá-lo
em outra rota não identifica ninguém.

### O código de convite: autorização, não identidade

A criação de imagens por pessoas de fora usa um **código de convite**
(`NB3-XXXX-XXXX`, em `data/invites.json`). É importante ser honesto sobre o que
ele é: um mecanismo de **autorização**, não de **autenticação de identidade**.
Sem um provedor externo de identidade (e-mail verificado, OAuth, a conta do
MOJ), o servidor não tem como saber *quem* é a pessoa do outro lado — o código
*é* a credencial, exatamente como o token de imagem e a chave de boot. A
"identidade" de quem cria uma imagem é, na prática, "a quem a administração
entregou aquele código".

Por isso o abuso é contido por **cota e limite de taxa**, e não por identidade:

- o código só cria `max_images` imagens e cada imagem só constrói `build_quota`
  camadas de pacotes (`server/app/services/invites.py`);
- as rotas públicas (`server/app/routers/public.py`) passam por um limite de
  taxa por IP (`server/app/services/ratelimit.py`), que só é confiável se o
  proxy repassar `X-Forwarded-For` — ver [operations.md](operations.md);
- nomes reservados (dígito inicial) e templates não-públicos são recusados na
  criação por convite.

Imagens criadas assim recebem `self_service: true` e a `build_quota` herdada do
código no `image.json`. O dono da imagem (o token dela) pode disparar builds de
camada da própria imagem até a cota — ver [layer-builds.md](layer-builds.md).

Quem não tem código deixa um pedido (`data/requests/<id>.json`), que a
administração aprova emitindo um código ou recusa. O pedido não cria nada
sozinho.

### A chave de boot

No NutellaBoot 2 os endpoints de boot eram completamente abertos: bastava
saber o nome da sede para baixar a configuração inteira e o script de boot. No
NutellaBoot 3 cada imagem tem uma **chave de boot** (`data/images/<id>/boot.key`),
que o pendrive carrega no `nutellaboot.conf` e envia a cada requisição. Sem
ela, o servidor não entrega manifest nem `stuff`.

A chave é aceita de três formas equivalentes, porque cada cliente tem sua
limitação: corpo de POST (`key=…`, que é o que o initrd usa com `wget`),
cabeçalho `X-NB-Boot-Key` (usado por `aria2c` e `curl`) e query string
(`?key=…`, conveniência para depuração). Por isso as rotas de boot aceitam
tanto `GET` quanto `POST`.

Duas exceções continuam abertas, de propósito:

- `/boot/v3/sanity` e `/boot/v3/time` — o teste de conectividade e a hora do
  servidor. O `/time` é consultado **sem** validar certificado, e é o único
  ponto em que isso acontece: ele existe justamente para corrigir o relógio de
  uma máquina com RTC zerado e assim tornar a validação de TLS possível na
  requisição seguinte.
- `/boot/v3/{img}/seeders/leave` — só sabe remover uma entrada do pool, o que é
  inócuo.

Uma imagem sem o arquivo `boot.key` volta a ser aberta. Isso é o modo de
depuração e desaparece assim que a imagem é criada pelo próprio nutellaboot3,
que sempre gera a chave. Ao rotacionar a chave
(`POST /api/v1/images/{img}/boot-key/rotate`), lembre-se de que **todo pendrive
daquela imagem precisa ter o `nutellaboot.conf` atualizado** — é um arquivo de
texto na partição FAT, mas ainda assim é preciso passar em cada um.

O transporte também mudou: o manifest e o `stuff` chegam por HTTPS com
certificado validado de verdade (bundle real embarcado no initrd), e cada
camada é conferida por md5. Por isso baixar a camada de um seeder por HTTP
simples continua seguro — a integridade vem do manifest, que veio por TLS.

Nada de credencial vaza pelos dados exibidos na tela de bloqueio: há teste
garantindo que `lockinfo` não devolva token, chave de máquina nem hash.

## Ciclo de vida dos seeders

Um seeder é uma máquina da própria sala que serve o cache já baixado para as
demais, acelerando o boot de um laboratório inteiro.

1. **Entrada** — `POST /boot/v3/{img}/seeders/join?ip=…&pw=<chave de máquina>`.
2. **Renovação** — o mesmo endpoint (`/heartbeat`) a cada 60 segundos, feito
   por um laço em segundo plano no `stuff`.
3. **Expiração** — `seeders.live()` descarta na leitura quem não renova há
   mais de `seeder_ttl_sec` (padrão: 180 s). Máquina desligada some sozinha.
4. **Saída explícita** — `/seeders/leave` remove na hora; não exige credencial
   porque só sabe remover uma entrada.

O manifest devolve **todas** as URLs de cada arquivo: todos os seeders vivos
(do heartbeat mais recente para o mais antigo) e o CDN por último. O `aria2c`
trata a lista como espelhos do mesmo arquivo e troca de fonte sozinho quando
uma falha.

No NutellaBoot 2 era o contrário: o servidor fazia rodízio e entregava **um**
servidor por requisição, com o arquivo `servers` sendo reescrito a cada acesso.
Não havia verificação de vida — um seeder desligado permanecia na lista até
alguém removê-lo à mão, e 1 de cada N máquinas da sala caía nele e gastava
todo o orçamento de tentativas antes de desistir.

## Canal de comandos

O requisito operacional é bloquear a tela da sala em menos de dez segundos sem
transformar o servidor em alvo de milhares de requisições.

O agente faz uma requisição que **fica pendurada**:

```
GET /api/v1/images/{img}/machines/{mac}/commands?wait=25
```

No servidor, `poll_commands` verifica a fila em disco; se estiver vazia, espera
em um `asyncio.Event` criado para aquela máquina. Quando alguém enfileira um
comando (`POST /commands`, `/lock`, `/unlock`), `notify.wake_machine()` acorda
o evento e a resposta sai imediatamente.

Dois detalhes importantes:

- **Teto de 25 s no cliente** (o servidor aceita até 30). Ao estourar, o agente
  simplesmente refaz a requisição. Isso mantém conexões saudáveis com qualquer
  proxy no caminho e dá cerca de **uma requisição por máquina a cada 25
  segundos** — menos carga que o polling de 5 a 30 segundos do nb2.
- **Reconferência a cada 5 s** — cada espera interna é limitada a 5 segundos,
  e ao acordar o disco é lido de novo. É a rede de segurança: mesmo que o sinal
  em memória se perca (processo reiniciado no meio, por exemplo), o pior caso é
  5 segundos, não 25.

Os eventos criados dentro da requisição, e não guardados em dicionário de longa
duração, são propositais: um `asyncio.Event` fica preso ao *event loop* em que
nasceu, e reutilizá-lo em outro loop levanta `RuntimeError`.

O bloqueio de tela usa **dois caminhos ao mesmo tempo**: grava
`lockstate.json` (que a própria tela de bloqueio consulta a cada poucos
segundos) e enfileira o comando `donottouch` para o agente. Se um falhar, o
outro resolve.

Medições da suíte de testes: bloqueio entregue em menos de 1,5 s numa máquina,
e 50 máquinas pendendo simultaneamente atendidas em menos de 3 s.

## Diferenças em relação ao NutellaBoot 2

| Assunto | NutellaBoot 2 | NutellaBoot 3 |
|---|---|---|
| Servidor | CGI em bash (`nb2.sh`, 209 linhas) com rotas em `PATH_INFO` | FastAPI, rotas REST com OpenAPI navegável |
| Estado | diretórios e arquivos soltos, escrita sem trava | mesmo formato, mas toda escrita atômica e travada |
| Seeders | rodízio de **um** servidor por boot, sem verificação de vida | **todos** os seeders vivos + CDN, com TTL por heartbeat |
| Latência de comando | mais de 30 s (polling de 5–30 s + atraso configurado) | menos de 2 s (long-poll), com no máximo 5 s no pior caso |
| Fila de comandos | um arquivo de texto por sede em `/tmp`, nunca truncado, servindo de fila e histórico | um arquivo por comando e por máquina, com confirmação e histórico com teto |
| Comandos permitidos | incluía `mlupdatecommands`, que baixava e executava script remoto sem autenticação | lista fixa no servidor; o comando de execução remota foi removido |
| Acesso ao boot | endpoints abertos: sabendo o nome da sede, qualquer um baixava configuração e script de boot | chave de boot por imagem, carregada no `nutellaboot.conf` do pendrive |
| TLS | `--check-certificate=false` em todo download | certificado validado sempre; relógio acertado antes, para não falhar por data errada |
| WiFi | suporte presente no initrd, mas desativado — o `stuff` sobrescrevia a função de rede e deixava de chamá-lo | rede é responsabilidade exclusiva do bootstrap, com espera real de associação; `wifi.conf` no pendrive é a fonte única |
| Configuração travada | dois diretórios de template mantidos à mão (`…` e `…-desbloqueado`) | campo `locked` no `schema.json`, com validação no servidor |
| Wallpaper | URL colada à mão; o servidor baixava ao salvar e uma URL ruim derrubava o salvamento inteiro (e podia travar o boot num prompt) | upload do arquivo, md5 calculado no envio; falha ao baixar nunca impede o boot |
| Camada extra | tar manual do overlay em RAM, poda manual, mksquashfs manual, md5 copiado à mão | construção automática sem root (`unshare` + `squashfuse` + `fuse-overlayfs` + `bwrap`), com poda automática |
| Credenciais em camada | camadas reais chegaram a ser publicadas com `/etc/shadow` dentro | poda neutraliza hashes de senha e remove backups de credencial |
| Vínculo time↔máquina | grafo de links simbólicos criado por CGI sem autenticação | roster + `binding.json`, com credencial e escopo |
| Tela de bloqueio | página remota fixa no código, com o prefixo da sede embutido; desbloqueio era matar o processo | temas locais (funciona sem rede), volta sozinha se for fechada, senha reserva configurável |
| Pendrive | uma imagem de 400 MB por sede (só mudava um parâmetro), gerada com root | uma imagem genérica; a sede é um arquivo de texto na partição, e a geração não precisa de root |
| Script de boot | 1130 linhas com condicionais por sede, incluindo senha de root fixa | módulos em `client/stuff/`, comportamento por variável de configuração |
| Interfaces | jQuery, só em inglês | JavaScript puro, português/inglês/espanhol |

## Onde continuar

- [api.md](api.md) — referência de rotas e integração com o MOJ
- `README.md` — como subir o ambiente e rodar os testes
- `client/stuff/` — o script de boot, um módulo por assunto
- `tools/` — geração de pendrive, imagem base, initrd, camadas e importação do nb2
