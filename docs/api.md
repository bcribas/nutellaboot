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
| Sub-administração | `NB3-` | `Authorization: Bearer NB3-XXXX-XXXX-XXXX` |
| Serviço (MOJ) | `nb3s_` | `Authorization: Bearer nb3s_…` |
| Site-image | `nb3i_` | `Authorization: Bearer nb3i_…` |
| Máquina | `nb3m_` | cabeçalho `X-NB-Machine-Key: nb3m_…` |
| Boot | `nb3b_` | POST `key=nb3b_…`, cabeçalho `X-NB-Boot-Key: nb3b_…` ou `?key=nb3b_…` |

A credencial de sub-administração **é o próprio código de convite** — não há
cadastro nem senha separada. Quem recebeu um código cria a imagem em
`/criar/` e volta com o mesmo código pelo console em `/admin/`. Revogar o
convite (`DELETE /api/v1/invites/{code}`) corta o acesso.

### Sessão do console (navegador)

As telas de administração não guardam credencial. A chave (de administração ou
o código de convite) é trocada uma vez por um **cookie de sessão**, e o
navegador cuida do resto — recarregar a página não pede nada de novo.

| Método | Caminho | Corpo | Resposta |
|---|---|---|---|
| POST | `/api/v1/session` | `{key}` | `Set-Cookie: nb3_session=…` + o mesmo corpo do `whoami` |
| GET | `/api/v1/session` | — | quem está logado, quando expira e as outras sessões desta identidade |
| DELETE | `/api/v1/session[?all=true]` | — | encerra esta sessão (ou todas as da identidade) |

O cookie é `HttpOnly` (nenhum script da página o lê), `Secure`,
`SameSite=Strict` e vale **30 dias**.

**Requisição autenticada por cookie precisa do cabeçalho `X-NB-Console: 1`.**
É o que impede CSRF: um `<form>` de outro site consegue fazer o navegador
mandar o cookie, mas não consegue definir cabeçalho, e um `fetch` cross-site
com cabeçalho próprio esbarra no *preflight*. Sem o cabeçalho, o cookie é
simplesmente ignorado.

Sessão é só para quem entra pelo console (`admin` e `subadmin`). Chave de
serviço, token de imagem e chave de máquina continuam **só no Bearer** — são
credenciais de programa, e nada mudou para elas: as ferramentas de linha de
comando e a integração do MOJ seguem exatamente iguais.

A sessão é revogável de verdade, porque a identidade é revalidada a cada
requisição: trocar a chave de administração, revogar o convite ou suspender o
sub-admin derruba as sessões na hora, mesmo dentro dos 30 dias.

Nas tabelas abaixo, a coluna **Cred.** usa: **A** administração, **C** console
(administração **ou** sub-administração), **S** serviço (com escopo), **I**
token da site-image, **M** chave de máquina, **B** chave de boot, **—** aberto.

> Rotas marcadas **C** respondem **404** — não 403 — quando o objeto é de
> outro dono. Um 403 confirmaria que o nome está tomado, e nomes são livres
> por ordem de chegada. Vale também para as rotas de uma site-image
> (`config`, `machines`, `roster`, `alerts`, `layers`): sem credencial é
> **401**, exista a imagem ou não; com credencial de outro dono, **404**.
> A chave de **serviço** é a exceção: como é a administração que a emite, ela
> recebe 403 de escopo ou de glob, que é o erro útil para quem integra.

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
| GET | `/api/v1/health` | — | `{"status","version","images","models","disk_free_gb"}` |
| GET | `/healthz` | — | `{"status":"ok"}` |
| GET | `/api/v1/events/types` | — | catálogo de eventos e escopos disponíveis |

### Site-images

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| POST | `/api/v1/site-images` | C | `{id, fullname, model, unlocked?, wallpaper_locked?}` | imagem criada **com as credenciais em claro** (única vez) |
| POST | `/api/v1/site-images/bulk` | A | TSV ou `{rows:[…]}` | `{results:[…]}`; com `?format=csv`, CSV das credenciais |
| GET | `/api/v1/site-images?prefix=` | C | — | `{images:[…]}` (o sub-admin vê só as dele) |
| GET | `/api/v1/site-images/{img}` | C, I | — | `image.json` |
| PATCH | `/api/v1/site-images/{img}` | C | `{fullname?, unlocked?, model?, wallpaper_locked?}` | imagem atualizada |
| DELETE | `/api/v1/site-images/{img}` | C | — | `204` |
| POST | `/api/v1/site-images/{img}/token/rotate` | C | — | `{token}` |
| GET | `/api/v1/site-images/{img}/credentials` | C | — | token, chaves e links prontos |
| GET | `/api/v1/site-images/{img}/boot-key` | C | — | `{boot_key}` |
| POST | `/api/v1/site-images/{img}/boot-key/rotate` | C | — | `{boot_key}` (exige atualizar os pendrives) |

Identificadores começando com dígito ficam no espaço reservado à
administração (`namespace: "contest"`); os demais são `personal`. O `id` aceita
2 a 32 caracteres em `[a-z0-9._-]`. **Sub-admins não criam nomes começando por
dígito nem nomes reservados** (`maratona`, `icpc`, `admin`, … — a lista está
em `reserved_names` no `data/server.json`); recebem 403 com a explicação.

Cada site-image guarda o campo `owner` (`"admin"` ou `"invite:<CÓDIGO>"`), que
é o que faz o console filtrar.

> **`/api/v1/site-images/…` continua respondendo, para sempre**, como alias de
> `/api/v1/site-images/…`. O agente de telemetria embarcado nas camadas já
> publicadas chama o caminho antigo, e não há como atualizá-lo remotamente. Não
> remova o alias (`LegacyImagePathMiddleware`, `server/app/main.py`).

### Modelos

Um **modelo** é o que se configura uma vez: as camadas (sistema base,
telemetria, wifi, pacotes) e o formulário que cada sede preenche
(`schema.json`, com o cadeado por campo). Toda site-image deriva de um modelo.

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| POST | `/api/v1/models` | C | `{name, description?, public?, from?}` | modelo criado |
| POST | `/api/v1/models/{n}/duplicate` | C | `{name, description?}` | cópia com as mesmas camadas e o mesmo formulário |
| GET | `/api/v1/models` | C | — | `{models:[{name, description, public, owner, mine, layers, used_by, can_manage}]}` |
| GET | `/api/v1/models/{n}` | C | — | `model.json` + `schema` |
| PATCH | `/api/v1/models/{n}` | C | `{public?, description?}` | modelo atualizado (só **A** publica) |
| DELETE | `/api/v1/models/{n}` | C | — | `204`; **409** se alguma site-image ainda deriva dele |
| POST | `/api/v1/models/{n}/layers` | C | `{file, md5, cdn_url?, size?, position?, role?, replace_role?}` | `{layers:[…]}` |
| DELETE | `/api/v1/models/{n}/layers/{file}` | C | — | `{layers:[…]}` |
| PUT | `/api/v1/models/{n}/layers/order` | C | `{files:[…]}` | `{layers:[…]}` |
| PUT | `/api/v1/models/{n}/layers` | C | `{layers:[…]}` | substitui a lista inteira (prefira o `POST`: uma leitura desatualizada aqui apaga o que outro acabou de acrescentar) |
| GET | `/api/v1/layers/catalog` | C | — | camadas já em uso, com `used_by` |
| GET | `/api/v1/models/{n}/schema` | C | — | campos com `default`, `label`, `help` e `locked` |
| PUT | `/api/v1/models/{n}/schema/locks` | C | `{locks:{CAMPO:true|false}}` | schema atualizado |
| PATCH | `/api/v1/models/{n}/schema/fields/{key}` | C | `{default?, locked?, label?, help?}` | schema atualizado |

Notas que economizam depuração:

- **A ordem das camadas é a prioridade no overlayfs — a primeira ganha.**
  `position: 0` (o padrão de `POST …/layers`) põe a camada na frente, que é
  quase sempre o que se quer para uma personalização.
- **`role`** diz o que a camada é: `base` (o sistema inteiro, sempre por
  último), `telemetry`, `wifi` ou `extra` (padrão). Valor fora dessa lista é
  recusado.
- **`replace_role: "base"`** troca a camada que tem aquele papel, mantendo a
  posição dela. É como se troca a base entre temporadas: casar por nome de
  arquivo não serve, porque o nome muda todo ano (`icpc-latam2025` →
  `maratonalinux2026`) e o modelo ficaria com as duas — a máquina baixaria as
  duas raízes e as montaria sobrepostas, sem erro em lugar nenhum.
- `from` (ou `duplicate`) copia camadas **e** formulário, cadeados inclusive.
  É o caminho para "quero um modelo novo que já tenha telemetria e wifi". A
  cópia é independente: mexer nela não mexe na origem.
- `PATCH …/schema/fields/{key}` ajusta um campo existente. Não cria campos:
  variável nova só teria efeito se algum módulo do `stuff` a lesse, o que é
  mudança de cliente. `label` e `help` exigem os três idiomas.
- Modelo sem camada nenhuma gera uma site-image que **não boota**; a criação
  devolve `warning` avisando disso.
- Só a administração marca um modelo como `public`. Modelo público é visível
  e derivável por todos os sub-admins, mas **somente leitura** para eles — se
  pudessem editá-lo, soltar um cadeado derrubaria a trava de todas as sedes
  que usam o mesmo modelo.

### Sub-administração

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| GET | `/api/v1/whoami` | C | — | `{kind, label, owner, can_create_reserved, can_publish_models, can_manage_invites, quotas, usage}` |
| GET | `/api/v1/owners` | A | — | `{owners:[{id, label, quotas, usage, console_ok}]}` |
| POST | `/api/v1/owners/{id}/disable` | A | `{disabled?: true}` | suspende (ou reativa) o console |
| PATCH | `/api/v1/owners/{id}/quotas` | A | `{max_models?, max_images?, build_quota?}` | `{id, quotas, usage}` |

`GET /api/v1/whoami` é o que a tela consulta ao abrir para saber o que
mostrar; sem ele o console descobriria as próprias permissões apanhando de
401/404.

**Cotas** vêm do convite (`max_models`, `max_images`, `build_quota`) e o uso é
contado **varrendo o disco**, não por contador: apagar um modelo libera a vaga
na hora, e nenhuma limpeza feita por fora deixa a cota travada por engano.

**Suspender × revogar.** `POST /owners/{id}/disable` corta o console e
preserva o histórico e o dono dos objetos. `DELETE /invites/{code}` apaga a
credencial: se o convite já criou alguma coisa, responde **409** listando o
que ficaria órfão e só prossegue com `?force=true`.

### Configuração e wallpaper

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| GET | `/api/v1/site-images/{img}/config` | C, I | — | `{image, schema, values, wallpaper, can_edit_locked}` |
| PUT | `/api/v1/site-images/{img}/config` | C, I, S`config:write` | `{values:{…}}` | `{ok, values}` |
| PUT | `/api/v1/site-images/{img}/wallpaper` | C, I, S`config:write` | multipart `file` | `{md5, size, filename, content_type}` |
| DELETE | `/api/v1/site-images/{img}/wallpaper` | C, I, S`config:write` | — | `204` |

Campos marcados como `locked` no esquema só aceitam escrita de administração
(ou se a imagem estiver marcada `unlocked`). Senhas nunca voltam pela API:
guardam-se apenas como hash com sal, e enviar vazio mantém a atual.

### Roster e vínculos

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| GET | `/api/v1/site-images/{img}/roster` | C, I, S`roster:read` | — | `{roster:[…]}` |
| PUT | `/api/v1/site-images/{img}/roster` | C, I, S`roster:write` | `{roster:[{user_id, name, display_name, organization, country, seat}]}` | `{ok, entries}` |
| PUT | `/api/v1/site-images/{img}/roster/logos/{org}` | C, I, S`roster:write` | multipart `file` (SVG ou PNG) | `{ok, org_id, format, size}` |
| PUT | `/api/v1/site-images/{img}/machines/{mac}/binding` | C, I, S`bindings:write` | `{user_id}` ou `{name, seat}` | vínculo criado |
| DELETE | `/api/v1/site-images/{img}/machines/{mac}/binding` | C, I, S`bindings:write` | — | `204` |
| GET | `/api/v1/site-images/{img}/bindings` | C, I, S`machines:read` | — | `{bindings:[{mac, …}]}` |

### Máquinas e telemetria

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| POST | `/api/v1/site-images/{img}/machines/{mac}/status` | M | JSON livre da telemetria (teto de 256 kB) | `{pending_commands, lock}` |
| GET | `/api/v1/site-images/{img}/machines` | C, I, S`machines:read` | — | `{machines:[…]}` |
| GET | `/api/v1/site-images/{img}/machines/{mac}` | C, I, S`machines:read` | — | estado completo da máquina |
| GET | `/api/v1/site-images/{img}/seeders` | C, I | — | `{seeders:[{ip, last_seen, ttl_left}]}` |
| DELETE | `/api/v1/site-images/{img}/seeders/{ip}` | C, I | — | `204` |

Cada máquina devolve `online`, `seconds_since_contact`, `status` (última
telemetria), `binding`, `lock`, `pending`, `logs` e `alerts`. O MAC é aceito
com `:` ou `-` e normalizado para minúsculas com hífen.

O corpo do `status` é JSON livre de propósito: um coletor novo em
`parts.d/` no cliente entra sem mudança no servidor. Livre não é infinito —
acima de 256 kB a resposta é **413**.

### Logs (journal do kernel e do sistema)

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| POST | `/api/v1/site-images/{img}/machines/{mac}/logs?origem=` | M | `text/plain`, até 1 MiB | `{ok, stored, at}` |
| GET | `/api/v1/site-images/{img}/machines/{mac}/logs?tail=500` | C, I, S`machines:read` | — | `{bytes, journal, acks}` |

O agente manda o journal do boot na partida e, a cada 5 minutos, só o que
apareceu desde o envio anterior (usando `journalctl --cursor-file`, que não
repete nem perde linha). Incremento vazio não vira requisição.

**Dois tetos, porque log enche disco em silêncio:** 1 MiB por requisição
(**413** acima disso) e 2 MiB por máquina, mantendo a cauda. 100 máquinas
cabem em 200 MB por construção.

O `GET` devolve também as confirmações de comando (`acks`), que até então
eram gravadas e não podiam ser lidas por rota nenhuma.

### Alertas (pendrive, celular, tethering)

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| POST | `/api/v1/site-images/{img}/machines/{mac}/events` | M | `{kind, detail?, vendor?}` | `{ok, id}` |
| GET | `/api/v1/site-images/{img}/alerts` | C, I, S`machines:read` | — | `{alerts:[…]}` abertos da sede |
| POST | `/api/v1/site-images/{img}/machines/{mac}/alerts/{id}/dismiss` | C, I, S`commands:write` | — | `{ok, alert}` |
| POST | `/api/v1/site-images/{img}/machines/{mac}/alerts/dismiss-all` | C, I, S`commands:write` | — | `{ok, dismissed}` |
| GET | `/api/v1/site-images/{img}/machines/{mac}/alerts/history` | C, I, S`machines:read` | — | `{history:[…]}` datado |

`kind` conhecido: `usb.storage` (pendrive, HD externo), `usb.phone` (MTP/PTP),
`usb.network` (tethering) e `usb.other`. Um `kind` desconhecido **é aceito** —
o cliente pode ganhar um detector novo sem esperar o servidor.

**O alerta fica até alguém dispensar.** Não some quando o dispositivo é
removido: quem espeta um pendrive por cinco segundos não escapa do registro.
Sobrevive a reboot da máquina, a recarga da página e a reinício do servidor
(está em disco). Dispensar grava quem foi e quando, no histórico.

A máquina **não** dispensa o próprio alerta: adulterar o agente não apaga o
rastro. O evento `alert.raised` também vai por webhook, para o MOJ.

### Comandos e bloqueio de tela

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| POST | `/api/v1/site-images/{img}/commands` | C, I, S`commands:write` | `{command, target, args?, delay?}` | `{command_id, machines}` |
| GET | `/api/v1/site-images/{img}/machines/{mac}/commands?wait=25` | M | — | `{commands:[…], lock}` (long-poll) |
| POST | `/api/v1/site-images/{img}/machines/{mac}/commands/{cid}/ack` | M | `{status, output?}` | `{ok, found}` |
| POST | `/api/v1/site-images/{img}/lock` · `/unlock` | C, I, S`commands:write` | — | `{command_id, machines, locked}` |
| POST | `/api/v1/site-images/{img}/machines/{mac}/lock` · `/unlock` | C, I, S`commands:write` | — | idem, para uma máquina |

`target` é `"all"` ou uma lista de MACs. `delay` adia a execução em segundos.
Comandos aceitos: `donottouch`, `cantouch`, `cleanhomenow`, `mlreboot`,
`mlpoweroff`, `disablefirewall`, `enablefirewall`, `resetcontaeditores`,
`precontest`. Qualquer outro valor é recusado com `400`.

O parâmetro `wait` (0 a 30 segundos) é o long-poll: a conexão fica aberta até
chegar comando ou estourar o tempo. O agente usa `wait=25`.

### Eventos em tempo real (SSE)

| Método | Caminho | Cred. | Resposta |
|---|---|---|---|
| GET | `/api/v1/site-images/{img}/events?tk=<token>` | C, I, S | fluxo `text/event-stream` |

O token vai na query porque `EventSource` não permite cabeçalhos. Formato de
cada evento:

```
event: machine.locked
data: {"machines": ["52-54-00-12-34-56"]}
```

Eventos: `machine.first_seen`, `machine.status`, `machine.locked`,
`machine.unlocked`, `machine.bound`, `machine.unbound`, `command.sent`,
`command.acked`, `config.updated`, `seeder.joined`, `alert.raised`,
`alert.dismissed`. A lista viva está em `GET /api/v1/events/types`. Linhas
`: ping` a cada 20 segundos mantêm a conexão viva.

### Camadas extras

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| POST | `/api/v1/layerbuilds` | C | `{name, model, packages:[…], attach_to?}` | job criado (sub-admin gasta `build_quota`) |
| GET | `/api/v1/layerbuilds` | C | — | `{builds:[{…, state}]}` (filtrado por dono) |
| GET | `/api/v1/layerbuilds/{job}` | C | — | job + últimos 8000 caracteres do log |
| POST | `/api/v1/layerbuilds/{job}/attach` | C | `{image_ids:[…]}` | `{ok, layer, images}` |
| GET | `/api/v1/site-images/{img}/layers` | C, I | — | `{extra:[…], all:[…]}` |
| POST | `/api/v1/site-images/{img}/layers` | C | `{md5, file, size?, cdn_url?}` | `{ok, layer}` |
| DELETE | `/api/v1/site-images/{img}/layers/{file}` | C | — | `204` |

Nomes de pacote são validados contra `^[a-z0-9][a-z0-9+._-]*$`, então não há
como injetar opções ou comandos. Camadas anexadas entram **no começo** da
lista, que é o que lhes dá prioridade no overlayfs.

### Pendrive de boot

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| GET | `/api/v1/usb` | A | — | `{kernel, generic, auto_generate, images:[…]}` |
| POST | `/api/v1/usb/generic` | A | — | `202` + estado (gera em segundo plano) |
| GET | `/api/v1/site-images/{img}/usb` | C, I | — | `{kernel, generic, image}` |
| POST | `/api/v1/site-images/{img}/usb` | C, I | — | `202` + estado |
| GET | `/api/v1/site-images/{img}/usb/conf` | C, I, `?tk=` | — | `nutellaboot.conf` (texto) |
| GET | `/api/v1/site-images/{img}/usb/image` | C, I, `?tk=` | — | a `.img` da sala |
| GET | `/api/v1/usb/generic/image` | C, `?id=&tk=` | — | a `.img` genérica |

Os três downloads aceitam a credencial na **query** porque um `<a download>` não
manda cabeçalho — a mesma exceção, e pelo mesmo motivo, da prévia do wallpaper e
do SSE. Nenhum deles passa pelo `/blobs`, que é servido sem autenticação: a
imagem de uma sala carrega a chave de boot dentro.

O estado de cada imagem é `missing`, `building`, `done`, `failed` ou
`unavailable` (falta o par kernel+initrd, que só se produz com root). Quando
`done`, vem também `stale` e `stale_reason` (`boot_key`, `kernel`, `server`),
calculados na leitura: rotacionar a chave de boot torna a imagem obsoleta sem
que ninguém precise avisar o serviço.

Quando a publicação está ligada, a resposta traz `public_url` no servidor de
arquivos e as telas usam essa URL — a máquina de gestão não serve 400 MB por
sede. A imagem genérica não leva segredo nenhum e pode ficar pública; a da sala
ganha um sufixo aleatório no nome por causa da chave que carrega.

### Publicação no servidor de arquivos

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| GET | `/api/v1/publish` | A | — | `{enabled, host, paths, base_urls, files:[…]}` |
| POST | `/api/v1/publish/retry` | A | — | `{retried, ok, files}` — reenvia o que não está `done` |
| POST | `/api/v1/publish/file` | A | `{file, kind}` | estado do envio (`kind`: `layers` ou `usb`) |

`file` é só o nome do arquivo (nunca um caminho): ele é resolvido dentro de
`data/blobs/` ou `data/usb/` conforme o `kind`.

### Webhooks e chaves de serviço

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| GET | `/api/v1/site-images/{img}/webhooks` | A | — | lista com o segredo mascarado (`***`) |
| PUT | `/api/v1/site-images/{img}/webhooks` | A | `{webhooks:[{url, secret, events}]}` | `{ok, webhooks}` |
| POST | `/api/v1/service-keys` | A | `{name, scopes:[…], images:[globs]}` | `{name, key, scopes, images}` |
| GET | `/api/v1/service-keys` | A | — | lista sem as chaves |
| DELETE | `/api/v1/service-keys/{nome}` | A | — | `204` |

Eventos disponíveis: `machine.first_seen`, `machine.status`, `machine.locked`, `machine.unlocked`, `machine.bound`, `machine.unbound`, `command.sent`, `command.acked`, `config.updated`, `seeder.joined`, `alert.raised` e `alert.dismissed` (a lista viva está em `GET /api/v1/events/types`).

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
curl -sS -X PUT https://nutellaboot.naquadah.com.br/api/v1/site-images/26brbr/roster \
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
  https://nutellaboot.naquadah.com.br/api/v1/site-images/26brbr/roster/logos/unb \
  -H "Authorization: Bearer $MOJ_KEY" \
  -F file=@unb.svg
```

Aceita SVG ou PNG, até 2 MB. O identificador da organização não pode conter
barra nem `..`.

### 4. Vincular o time à máquina

```bash
curl -sS -X PUT \
  https://nutellaboot.naquadah.com.br/api/v1/site-images/26brbr/machines/52-54-00-12-34-56/binding \
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
curl -sS -X POST https://nutellaboot.naquadah.com.br/api/v1/site-images/26brbr/lock \
  -H "Authorization: Bearer $MOJ_KEY"

# uma máquina
curl -sS -X POST \
  https://nutellaboot.naquadah.com.br/api/v1/site-images/26brbr/machines/52-54-00-12-34-56/unlock \
  -H "Authorization: Bearer $MOJ_KEY"
```

Resposta: `{"command_id":"a1b2c3d4e5f6","machines":42,"locked":true}`. As
máquinas recebem em poucos segundos, porque estão penduradas no long-poll.

### 6. Ler telemetria

```bash
curl -sS https://nutellaboot.naquadah.com.br/api/v1/site-images/26brbr/machines \
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
curl -sS -X PUT https://nutellaboot.naquadah.com.br/api/v1/site-images/26brbr/webhooks \
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
| `404` | imagem, modelo, job ou recurso inexistente |
| `413` | arquivo grande demais (wallpaper acima de 12 MB, logotipo acima de 2 MB) |

O corpo do erro segue o padrão do FastAPI: `{"detail": "mensagem em português"}`.
