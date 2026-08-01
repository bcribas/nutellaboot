# Referência da API

O NutellaBoot 3 expõe duas famílias de endpoints:

- **`/boot/v3/…`** — texto puro, consumido pelo initramfs, pelo agente e pela
  tela de bloqueio. É texto porque quem lê é shell sem `jq`.
- **`/api/v1/…`** — JSON, consumido pelas telas web e por sistemas externos
  como o MOJ.

Há ainda a documentação interativa gerada automaticamente em
**`/api/v1/docs`** (OpenAPI navegável, com formulário para testar cada rota) e
o esquema cru em `/api/v1/openapi.json`.

## Credenciais

| Classe | Prefixo | Como enviar |
|---|---|---|
| Administração | `nb3a_` | `Authorization: Bearer nb3a_…` |
| Serviço (MOJ) | `nb3s_` | `Authorization: Bearer nb3s_…` |
| Imagem | `nb3i_` | `Authorization: Bearer nb3i_…` |
| Máquina | `nb3m_` | cabeçalho `X-NB-Machine-Key: nb3m_…` |
| Boot | `nb3b_` | POST `key=nb3b_…`, cabeçalho `X-NB-Boot-Key: nb3b_…` ou `?key=nb3b_…` |

Nas tabelas abaixo, a coluna **Cred.** usa: **A** administração, **S** serviço
(com escopo), **I** token da imagem, **M** chave de máquina, **B** chave de
boot, **—** aberto.

---

## Endpoints de boot (`/boot/v3`)

Todos respondem `text/plain`, exceto `lockinfo` (JSON) e os arquivos binários.
As rotas marcadas com **B** aceitam `GET` e `POST` — o initrd usa `POST` para
mandar a chave no corpo; `aria2c` e `curl` usam o cabeçalho.

| Método | Caminho | Cred. | Quem consome | Resposta |
|---|---|---|---|---|
| GET | `/boot/v3/sanity` | — | initrd | `penguin` |
| GET | `/boot/v3/time` | — | initrd | epoch em segundos, ex. `1785621130` |
| GET/POST | `/boot/v3/{img}/manifest` | B | initrd (`stuff`) | uma linha por camada: `MD5 ARQUIVO URL1 URL2 …` |
| GET/POST | `/boot/v3/{img}/stuff` | B | initrd | o script de boot completo, em shell |
| POST | `/boot/v3/{img}/seeders/join?ip=…` | B | `stuff` | `ok` |
| POST | `/boot/v3/{img}/seeders/heartbeat?ip=…` | B | `stuff` (a cada 60 s) | `ok` |
| POST | `/boot/v3/{img}/seeders/leave?ip=…` | — | `stuff` | `ok` |
| GET/POST | `/boot/v3/{img}/wallpaper` | B | `stuff` | PNG/JPEG, com `ETag` = md5 |
| GET/POST | `/boot/v3/{img}/lockinfo/{mac}` | B | tela de bloqueio | JSON com time, organização, país e lugar |
| GET/POST | `/boot/v3/{img}/machines/{mac}/lockstate` | B | tela de bloqueio (a cada 4 s) | `locked` ou `unlocked` |
| GET/POST | `/boot/v3/{img}/roster/logos/{org}` | B | tela de bloqueio | SVG ou PNG do logotipo |

### Exemplo: manifest

```
$ curl -s -H "X-NB-Boot-Key: $BOOT_KEY" \
    https://nutellaboot.naquadah.com.br/boot/v3/25brbr/manifest
60782353ebd1898ab5d5f7a86c9efc34 firefox.squash https://files.mdp.naquadah.com.br/maratonalinux/firefox.squash
2c02aa5ea909e9f74ce47ea7d3a84b4d wifis.squash http://files.mdp.naquadah.com.br/maratonalinux/wifis.squash
fbd0543ae7c9181ac029192e3c7d087e log23.squash http://files.mdp.naquadah.com.br/maratonalinux/log23.squash
65af7921bb82cd320f6cacd8551b3511 icpc-latam2025.squash-2025-08-01-11-48 http://files.mdp.naquadah.com.br/maratonalinux/icpc-latam2025.squash-2025-08-01-11-48
```

Com seeders ativos na sala, cada linha ganha as URLs deles **antes** do CDN:

```
b3d1… extra.squash http://10.0.51.58/extra.squash http://10.0.51.136/extra.squash https://files.mdp…/extra.squash
```

O cliente lê com `while read MD5 ARQUIVO URLS` e passa `$URLS` inteiro ao
`aria2c`, que trata a lista como espelhos do mesmo arquivo.

### Exemplo: lockinfo

```json
{
  "site": "FINALS SEDE: Brazilian Finals",
  "image": "25brbr",
  "mac": "52-54-00-12-34-56",
  "seat": "012",
  "team": { "name": "Os Batatinhas", "display_name": "UnB — Os Batatinhas" },
  "organization": {
    "id": "unb",
    "name": "Universidade de Brasília",
    "logo_url": "/boot/v3/25brbr/roster/logos/unb"
  },
  "country": "BRA"
}
```

### Exemplo: cabeçalho do `stuff`

```sh
#!/bin/sh
# nutellaboot3 stuff — imagem 25brbr — gerado em 2026-08-01 22:12:10 UTC
# Este arquivo é baixado e sourced pelo initrd a cada boot.

NBUID=866112933
IMAGEROOT='25brbr'
NB_SERVER='https://nutellaboot.naquadah.com.br'
NB_MACHINE_KEY='nb3m_…'
NB_BOOT_KEY='nb3b_…'
ALLOWNETWORKCHANGE='f'
…
```

---

## API JSON (`/api/v1`)

### Saúde

| Método | Caminho | Cred. | Resposta |
|---|---|---|---|
| GET | `/api/v1/health` | — | `{"status","version","images","disk_free_gb"}` |
| GET | `/healthz` | — | `{"status":"ok"}` |
| GET | `/api/v1/events/types` | — | catálogo de eventos e escopos disponíveis |

### Imagens

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| POST | `/api/v1/images` | A | `{id, fullname, template, unlocked?}` | imagem criada **com as credenciais em claro** (única vez) |
| POST | `/api/v1/images/bulk` | A | TSV ou `{rows:[…]}` | `{results:[…]}`; com `?format=csv`, CSV das credenciais |
| GET | `/api/v1/images?prefix=` | A | — | `{images:[…]}` |
| GET | `/api/v1/images/{img}` | A, I | — | `image.json` |
| PATCH | `/api/v1/images/{img}` | A | `{fullname?, unlocked?, template?}` | imagem atualizada |
| DELETE | `/api/v1/images/{img}` | A | — | `204` |
| POST | `/api/v1/images/{img}/token/rotate` | A | — | `{token}` |
| GET | `/api/v1/images/{img}/boot-key` | A | — | `{boot_key}` |
| POST | `/api/v1/images/{img}/boot-key/rotate` | A | — | `{boot_key}` (exige atualizar os pendrives) |

Identificadores começando com dígito ficam no espaço reservado à
administração (`namespace: "contest"`); os demais são `personal`. O `id` aceita
2 a 32 caracteres em `[a-z0-9._-]`.

### Templates

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| GET | `/api/v1/templates` | A | — | `{templates:[nomes]}` |
| GET | `/api/v1/templates/{nome}` | A | — | camadas + `schema` do formulário |
| PUT | `/api/v1/templates/{nome}/layers` | A | `{layers:[{md5,file,cdn_url,size}]}` | `{ok, layers}` |

### Configuração e wallpaper

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| GET | `/api/v1/images/{img}/config` | A, I | — | `{image, schema, values, wallpaper, can_edit_locked}` |
| PUT | `/api/v1/images/{img}/config` | A, I, S`config:write` | `{values:{…}}` | `{ok, values}` |
| PUT | `/api/v1/images/{img}/wallpaper` | A, I, S`config:write` | multipart `file` | `{md5, size, filename, content_type}` |
| DELETE | `/api/v1/images/{img}/wallpaper` | A, I, S`config:write` | — | `204` |

Campos marcados como `locked` no esquema só aceitam escrita de administração
(ou se a imagem estiver marcada `unlocked`). Senhas nunca voltam pela API:
guardam-se apenas como hash com sal, e enviar vazio mantém a atual.

### Roster e vínculos

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| GET | `/api/v1/images/{img}/roster` | A, I, S`roster:read` | — | `{roster:[…]}` |
| PUT | `/api/v1/images/{img}/roster` | A, I, S`roster:write` | `{roster:[{user_id, name, display_name, organization, country, seat}]}` | `{ok, entries}` |
| PUT | `/api/v1/images/{img}/roster/logos/{org}` | A, I, S`roster:write` | multipart `file` (SVG ou PNG) | `{ok, org_id, format, size}` |
| PUT | `/api/v1/images/{img}/machines/{mac}/binding` | A, I, S`bindings:write` | `{user_id}` ou `{name, seat}` | vínculo criado |
| DELETE | `/api/v1/images/{img}/machines/{mac}/binding` | A, I, S`bindings:write` | — | `204` |
| GET | `/api/v1/images/{img}/bindings` | A, I, S`machines:read` | — | `{bindings:[{mac, …}]}` |

### Máquinas e telemetria

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| POST | `/api/v1/images/{img}/machines/{mac}/status` | M | JSON livre da telemetria | `{pending_commands, lock}` |
| GET | `/api/v1/images/{img}/machines` | A, I, S`machines:read` | — | `{machines:[…]}` |
| GET | `/api/v1/images/{img}/machines/{mac}` | A, I, S`machines:read` | — | estado completo da máquina |
| GET | `/api/v1/images/{img}/seeders` | A, I | — | `{seeders:[{ip, last_seen, ttl_left}]}` |
| DELETE | `/api/v1/images/{img}/seeders/{ip}` | A, I | — | `204` |

Cada máquina devolve `online`, `seconds_since_contact`, `status` (última
telemetria), `binding`, `lock` e `pending`. O MAC é aceito com `:` ou `-` e
normalizado para minúsculas com hífen.

### Comandos e bloqueio de tela

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| POST | `/api/v1/images/{img}/commands` | A, I, S`commands:write` | `{command, target, args?, delay?}` | `{command_id, machines}` |
| GET | `/api/v1/images/{img}/machines/{mac}/commands?wait=25` | M | — | `{commands:[…], lock}` (long-poll) |
| POST | `/api/v1/images/{img}/machines/{mac}/commands/{cid}/ack` | M | `{status, output?}` | `{ok, found}` |
| POST | `/api/v1/images/{img}/lock` · `/unlock` | A, I, S`commands:write` | — | `{command_id, machines, locked}` |
| POST | `/api/v1/images/{img}/machines/{mac}/lock` · `/unlock` | A, I, S`commands:write` | — | idem, para uma máquina |

`target` é `"all"` ou uma lista de MACs. `delay` adia a execução em segundos.
Comandos aceitos: `donottouch`, `cantouch`, `cleanhomenow`, `mlreboot`,
`mlpoweroff`, `disablefirewall`, `enablefirewall`, `resetcontaeditores`,
`precontest`. Qualquer outro valor é recusado com `400`.

O parâmetro `wait` (0 a 30 segundos) é o long-poll: a conexão fica aberta até
chegar comando ou estourar o tempo. O agente usa `wait=25`.

### Eventos em tempo real (SSE)

| Método | Caminho | Cred. | Resposta |
|---|---|---|---|
| GET | `/api/v1/images/{img}/events?tk=<token>` | A, I, S | fluxo `text/event-stream` |

O token vai na query porque `EventSource` não permite cabeçalhos. Formato de
cada evento:

```
event: machine.locked
data: {"machines": ["52-54-00-12-34-56"]}
```

Eventos: `machine.first_seen`, `machine.status`, `machine.locked`,
`machine.unlocked`, `machine.bound`, `machine.unbound`, `command.sent`,
`command.acked`, `config.updated`, `seeder.joined`. Linhas `: ping` a cada 20
segundos mantêm a conexão viva.

### Camadas extras

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| POST | `/api/v1/layerbuilds` | A | `{name, template, packages:[…], attach_to?}` | job criado |
| GET | `/api/v1/layerbuilds` | A | — | `{builds:[{…, state}]}` |
| GET | `/api/v1/layerbuilds/{job}` | A | — | job + últimos 8000 caracteres do log |
| POST | `/api/v1/layerbuilds/{job}/attach` | A | `{image_ids:[…]}` | `{ok, layer, images}` |
| GET | `/api/v1/images/{img}/layers` | A, I | — | `{extra:[…], all:[…]}` |
| POST | `/api/v1/images/{img}/layers` | A | `{md5, file, size?, cdn_url?}` | `{ok, layer}` |
| DELETE | `/api/v1/images/{img}/layers/{file}` | A | — | `204` |

Nomes de pacote são validados contra `^[a-z0-9][a-z0-9+._-]*$`, então não há
como injetar opções ou comandos. Camadas anexadas entram **no começo** da
lista, que é o que lhes dá prioridade no overlayfs.

### Webhooks e chaves de serviço

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| GET | `/api/v1/images/{img}/webhooks` | A | — | lista com o segredo mascarado (`***`) |
| PUT | `/api/v1/images/{img}/webhooks` | A | `{webhooks:[{url, secret, events}]}` | `{ok, webhooks}` |
| POST | `/api/v1/service-keys` | A | `{name, scopes:[…], images:[globs]}` | `{name, key, scopes, images}` |
| GET | `/api/v1/service-keys` | A | — | lista sem as chaves |
| DELETE | `/api/v1/service-keys/{nome}` | A | — | `204` |

`events` vazio significa "todos os eventos". A URL precisa começar com
`http://` ou `https://`, e cada evento é validado contra o catálogo.

---

## Integração com o MOJ

O MOJ pode tanto **consultar** a API quanto **receber** eventos por webhook.
Os exemplos abaixo usam a sede `26brbr`.

### 1. Criar a chave de serviço

Feito uma vez, pela administração. Os escopos limitam o que a chave faz, e
`images` limita onde ela age.

```bash
curl -sS -X POST https://nutellaboot.naquadah.com.br/api/v1/service-keys \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
        "name": "moj",
        "scopes": ["machines:read", "commands:write",
                   "bindings:write", "roster:read", "roster:write"],
        "images": ["26*"]
      }'
```

Resposta (a chave aparece **uma única vez**):

```json
{"name":"moj","key":"nb3s_…","scopes":["machines:read","…"],"images":["26*"]}
```

### 2. Enviar o roster dos times

```bash
curl -sS -X PUT https://nutellaboot.naquadah.com.br/api/v1/images/26brbr/roster \
  -H "Authorization: Bearer $MOJ_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
        "roster": [
          {
            "user_id": "team-001",
            "name": "Os Batatinhas",
            "display_name": "UnB — Os Batatinhas",
            "organization": {"id": "unb", "name": "Universidade de Brasília"},
            "country": "BRA",
            "seat": "012"
          }
        ]
      }'
```

### 3. Enviar o logotipo da instituição

```bash
curl -sS -X PUT \
  https://nutellaboot.naquadah.com.br/api/v1/images/26brbr/roster/logos/unb \
  -H "Authorization: Bearer $MOJ_KEY" \
  -F file=@unb.svg
```

Aceita SVG ou PNG, até 2 MB. O identificador da organização não pode conter
barra nem `..`.

### 4. Vincular o time à máquina

```bash
curl -sS -X PUT \
  https://nutellaboot.naquadah.com.br/api/v1/images/26brbr/machines/52-54-00-12-34-56/binding \
  -H "Authorization: Bearer $MOJ_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "team-001"}'
```

O `user_id` precisa existir no roster da imagem, senão a resposta é `404`. A
partir daí a tela de bloqueio daquela máquina mostra o nome do time, o
logotipo, a bandeira e o lugar.

### 5. Bloquear e desbloquear

```bash
# a sala inteira
curl -sS -X POST https://nutellaboot.naquadah.com.br/api/v1/images/26brbr/lock \
  -H "Authorization: Bearer $MOJ_KEY"

# uma máquina
curl -sS -X POST \
  https://nutellaboot.naquadah.com.br/api/v1/images/26brbr/machines/52-54-00-12-34-56/unlock \
  -H "Authorization: Bearer $MOJ_KEY"
```

Resposta: `{"command_id":"a1b2c3d4e5f6","machines":42,"locked":true}`. As
máquinas recebem em poucos segundos, porque estão penduradas no long-poll.

### 6. Ler telemetria

```bash
curl -sS https://nutellaboot.naquadah.com.br/api/v1/images/26brbr/machines \
  -H "Authorization: Bearer $MOJ_KEY"
```

```json
{"machines": [
  {
    "mac": "52-54-00-12-34-56",
    "online": true,
    "seconds_since_contact": 12,
    "lock": {"locked": false, "since": 1785620000, "by": "moj"},
    "binding": {"user_id": "team-001", "seat": "012"},
    "pending": 0,
    "status": {
      "hwinfo": {"processor": "…", "cores": 8, "memtotal_mb": 15900},
      "sysresources": {"mem_pct": 41, "loadavg": [0.6, 0.4, 0.3], "alerts": []},
      "operations": {"firewall": true, "screen_lock": false, "editors": ["code"]}
    }
  }
]}
```

### 7. Receber eventos por webhook

Configuração (pela administração):

```bash
curl -sS -X PUT https://nutellaboot.naquadah.com.br/api/v1/images/26brbr/webhooks \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
        "webhooks": [
          {
            "url": "https://moj.naquadah.com.br/hooks/nutellaboot",
            "secret": "um-segredo-combinado",
            "events": ["machine.first_seen", "machine.locked", "machine.unlocked"]
          }
        ]
      }'
```

Cada evento chega como `POST` com corpo JSON e o cabeçalho
`X-NB-Signature: sha256=<HMAC-SHA256 do corpo, com o segredo>`:

```json
{
  "event": "machine.locked",
  "image": "26brbr",
  "at": 1785620123.45,
  "data": {"machines": ["52-54-00-12-34-56"]}
}
```

Verificação no lado do MOJ:

```python
import hashlib
import hmac

def assinatura_confere(corpo: bytes, cabecalho: str, segredo: str) -> bool:
    """corpo = bytes crus da requisição, ANTES de qualquer parse."""
    esperado = "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, cabecalho or "")
```

A entrega é de melhor esforço: até três tentativas, com espera crescente e
tempo limite de 5 segundos cada. Um webhook lento nunca segura o boot nem o
comando de bloqueio — o envio acontece em segundo plano.

---

## Códigos de erro

| Código | Quando |
|---|---|
| `400` | dados inválidos (comando fora da lista, MAC malformado, campo desconhecido, pacote com nome suspeito) |
| `401` | credencial ausente, inválida ou chave de boot errada |
| `403` | credencial válida sem escopo suficiente, ou sem acesso àquela imagem |
| `404` | imagem, template, job ou recurso inexistente |
| `413` | arquivo grande demais (wallpaper acima de 12 MB, logotipo acima de 2 MB) |

O corpo do erro segue o padrão do FastAPI: `{"detail": "mensagem em português"}`.
