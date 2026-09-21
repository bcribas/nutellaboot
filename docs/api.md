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
| GET | `/api/v1/session` | — | quem está logado, quando expira (já renovado, se esta requisição renovou) e as outras sessões desta identidade |
| DELETE | `/api/v1/session[?all=true]` | — | encerra esta sessão (ou todas as da identidade) |

O cookie é `HttpOnly` (nenhum script da página o lê), `Secure`,
`SameSite=Strict` e vale **30 dias a partir do último uso**: uma requisição
de console feita mais de 24 h depois da última renovação estende o prazo e
reemite o cookie (`Set-Cookie` na própria resposta); `sessions.json` é
reescrito no máximo uma vez por dia por sessão. Só requisição de console
renova — `<img>`, `<a download>` e `EventSource` não recebem cookie de volta.

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
>
> **401 × 403 para a chave de serviço.** `401` é só para credencial que não
> vale (ausente, errada, revogada). Uma chave de serviço **válida** que bate
> numa rota do console recebe `403` com `code: "console_only"`; sem o escopo,
> `insufficient_scope`; fora do glob, `image_out_of_scope`. Ela também não
> gasta o limitador de tentativas do console.

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
| POST | `/boot/v3/{img}/seeders/join?ip=…` | B | `stuff` | `accepted=t\|f` + `seeders=N` |
| POST | `/boot/v3/{img}/seeders/heartbeat?ip=…` | B | `stuff` (a cada 60 s) | `released=t\|f` + `seeders=N` |
| POST | `/boot/v3/{img}/seeders/leave?ip=…` | — | `stuff` | `ok` |
| GET/POST | `/boot/v3/{img}/wallpaper` | B | `stuff` | PNG/JPEG, com `ETag` = md5 |
| GET/POST | `/boot/v3/{img}/clionkey` | B | `stuff` | a licença do CLion (404 se não instalada no servidor) |
| GET/POST | `/boot/v3/{img}/lockinfo/{mac}` | B | tela de bloqueio | JSON com time, organização, país e lugar |
| GET/POST | `/boot/v3/{img}/machines/{mac}/lockstate` | B | tela de bloqueio (a cada 4 s) | `locked` ou `unlocked` |
| GET/POST | `/boot/v3/{img}/roster/logos/{org}` | B | tela de bloqueio | SVG ou PNG do logotipo |
| GET/POST | `/boot/v3/{img}/usb` | B | `stuff` | `BUILD <id>` e, nas linhas seguintes, `MD5 ARQUIVO URL` (mesmo formato do manifest) |
| GET/POST | `/boot/v3/{img}/usbfile/{nome}` | B | `stuff` | o `vmlinuz` ou o `initrd.img` da construção atual |

O join respeita o limite `SEEDMAX` da configuração da imagem (padrão 4):
pool cheio responde **200 com `accepted=f`** — não é erro, a máquina só pula
a semeadura e boota direto. `released=t` no heartbeat avisa que o console
liberou a máquina: ela sai do modo seed, chama `leave` e termina o boot.
Tudo em texto puro `chave=valor`, como o resto do `/boot/v3`.

`/usb` é como a máquina descobre que o pendrive de onde ela bootou está para
trás: o initrd carrega o próprio carimbo em `/etc/nutellaboot-build`, compara,
e se for diferente baixa os arquivos, confere o md5 e regrava a partição
sozinho. Construção sem `client/build/build.json` responde `BUILD unknown`, e
aí a máquina não confere nada. `{nome}` sai de uma lista fechada
(`vmlinuz`, `initrd.img`). Veja `docs/boot-flow.md`.

### Exemplo: manifest

```
$ curl -s -H "X-NB-Boot-Key: $BOOT_KEY" \
    https://nutellaboot.mdp.naquadah.com.br/boot/v3/25brbr/manifest
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
  "country": "BR"
}
```

### Exemplo: cabeçalho do `stuff`

```sh
#!/bin/sh
# nutellaboot3 stuff — imagem 25brbr — gerado em 2026-08-01 22:12:10 UTC
# Este arquivo é baixado e sourced pelo initrd a cada boot.

NBUID=866112933
IMAGEROOT='25brbr'
NB_SERVER='https://nutellaboot.mdp.naquadah.com.br'
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
| POST | `/api/v1/site-images` | C | `{id, fullname, model, unlocked?, wallpaper_locked?, dashboard_hidden?, country?}` (`dashboard_hidden` só a administração; `country` é ISO alpha-2) | imagem criada **com as credenciais em claro** (única vez) |
| POST | `/api/v1/site-images/bulk` | A | TSV ou `{rows:[…]}` | `{results:[…]}`; com `?format=csv`, CSV das credenciais |
| GET | `/api/v1/site-images?prefix=` | C, S (qualquer escopo) | — | `{images:[…]}` (o sub-admin vê só as dele). Para a chave de serviço: só as imagens do glob, como `{id, fullname, country?, machines_total}` |
| GET | `/api/v1/site-images/{img}` | C, I, S (qualquer escopo, dentro do glob) | — | `image.json` **sem o `owner` cru** para quem não é o console dono (ver abaixo); sempre com `owner_kind`, `owner_label`, `owner_ref` |
| PATCH | `/api/v1/site-images/{img}` | C | `{fullname?, unlocked?, model?, wallpaper_locked?, dashboard_hidden?}` | imagem atualizada |
| DELETE | `/api/v1/site-images/{img}` | C | — | `204` (apaga também o pendrive gerado em `data/usb/` e o estado de publicação) |
| POST | `/api/v1/site-images/{img}/token/rotate` | C | — | `{token}` |
| GET | `/api/v1/site-images/{img}/credentials` | C | — | token, chaves e links prontos |
| GET | `/api/v1/site-images/{img}/boot-key` | C | — | `{boot_key}` |
| POST | `/api/v1/site-images/{img}/boot-key/rotate` | C | — | `{boot_key}` (exige atualizar os pendrives) |

> **O dono de uma imagem e o código do convite.** O id do dono de um sub-admin é
> `invite:<CÓDIGO>`, e o código é a credencial de console dele. Por isso o
> `owner` cru só é devolvido à administração e ao próprio dono. Para o token da
> sede, a chave de serviço e outro sub-admin (num modelo público), a resposta
> traz `owner_kind` (`admin` ou `subadmin`), `owner_label` (o rótulo do convite)
> e `owner_ref` (uma referência curta, que não se reverte ao código). Vale
> também para `GET /api/v1/models` e `GET /api/v1/models/{nome}`.

`dashboard_hidden` (só a administração muda) tira a imagem das visões da frota
(`/labs`, `/labs/inventory`, `/labs/series`): é para a imagem de teste dos
times, que não pode inflar o placar nem o perfil de hardware. Ela continua
existindo em tudo o mais (hotconfig, configureitor, relatório).

Identificadores começando com dígito ficam no espaço reservado à
administração (`namespace: "contest"`); os demais são `personal`. O `id` aceita
2 a 32 caracteres em `[a-z0-9._-]`. **Sub-admins não criam nomes começando por
dígito nem nomes reservados** (`maratona`, `icpc`, `admin`, … — a lista está
em `reserved_names` no `data/server.json`); recebem 403 com a explicação.

Cada site-image guarda o campo `owner` (`"admin"` ou `"invite:<CÓDIGO>"`), que
é o que faz o console filtrar.

**A criação em massa devolve OS DOIS links da sede.** São duas telas —
`/configureitor/` (formulário e papel de parede) e `/hotconfig/` (laboratório
durante a prova) — e as duas usam o mesmo `?id=&tk=`. O CSV sai assim:

```
id,ok,token,machine_key,boot_key,configureitor_url,hotconfig_url,error
```

Quem prefere não montar `curl` na mão tem o cliente de referência:

```bash
tools/nb3-api bulk sedes.tsv > credenciais.csv
```

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
| GET | `/api/v1/whoami` | C, S (qualquer escopo) | — | console: `{kind, label, owner, can_create_reserved, can_publish_models, can_manage_invites, quotas, usage}`; chave de serviço: `{kind:"service", name, label, scopes, image_globs, images}` |
| GET | `/api/v1/owners` | A | — | `{owners:[{id, label, quotas, usage, console_ok}]}` |
| POST | `/api/v1/owners/{id}/disable` | A | `{disabled?: true}` | suspende (ou reativa) o console |
| PATCH | `/api/v1/owners/{id}/quotas` | A | `{max_models?, max_images?, build_quota?}` | `{id, quotas, usage}` |

**Convites** — a credencial de sub-administração é o próprio código:

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| GET | `/api/v1/invites` | A | — | `{invites:[…]}` |
| POST | `/api/v1/invites` | A | `{label?, note?, model?, count?, max_images?, max_models?, build_quota?, expires_at?, unlocked?, wallpaper_locked?}` | `{invites:[…]}` — **com os códigos**; `count` emite vários de uma vez |
| DELETE | `/api/v1/invites/{code}` | A | — | **409** listando o que ficaria órfão; `?force=true` apaga assim mesmo |

`unlocked` no convite escolhe o perfil da imagem que ele vai criar: **Livre**
(o dono manda em tudo) ou **Oficial** (valem os cadeados do modelo). `model`
prende o convite a um modelo só.

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

### Auto-atendimento e pedidos

Quem tem um código de convite cria a própria imagem sem passar pela
administração; quem não tem, pede um. Estas três rotas são as **únicas sem
credencial** da API, e por isso são as únicas com limite por IP.

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| GET | `/api/v1/public/models` | — | — | `{models:[…]}` — só os marcados `public` |
| POST | `/api/v1/public/site-images` | — | `{code, id, fullname, model?}` | imagem criada **com as credenciais em claro** |
| POST | `/api/v1/public/requests` | — | `{wanted_name, contact, note?}` | `{ok, id}` |

O `model` do corpo só é considerado quando o convite não prende um; nome
começando por dígito é recusado com 403 (espaço reservado à administração).

Do outro lado, a administração despacha os pedidos:

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| GET | `/api/v1/requests` | A | — | `{requests:[…]}` |
| POST | `/api/v1/requests/{rid}/approve` | A | `{action:"issue_code"\|"create", model?, max_images?, build_quota?, unlocked?}` | o código emitido, ou a imagem já criada com as credenciais |
| POST | `/api/v1/requests/{rid}/reject` | A | `{reason?}` | pedido marcado como recusado |

`issue_code` devolve um convite para a pessoa se virar; `create` já cria a
imagem e devolve as credenciais para repassar.

### Configuração e wallpaper

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| GET | `/api/v1/site-images/{img}/config` | C, I | — | `{image, schema, values, wallpaper, can_edit_locked}` |
| PUT | `/api/v1/site-images/{img}/config` | C, I, S`config:write` | `{values:{…}}` | `{ok, values}` |
| PUT | `/api/v1/site-images/{img}/wallpaper` | C, I, S`config:write` | multipart `file` | `{md5, size, filename, content_type}` |
| DELETE | `/api/v1/site-images/{img}/wallpaper` | C, I, S`config:write` | — | `204` |
| GET | `/api/v1/site-images/{img}/wallpaper` | C, I (`?tk=` ou cookie) | — | o arquivo, para a prévia |

Campos marcados como `locked` no esquema só aceitam escrita de administração
(ou se a imagem estiver marcada `unlocked`). Senhas nunca voltam pela API:
guardam-se apenas como hash com sal, e enviar vazio mantém a atual.

**O papel de parede pode vir do MODELO.** A organização define um no modelo e
toda sede dele passa a usá-lo:

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| PUT | `/api/v1/models/{nome}/wallpaper` | C (dono do modelo) | multipart `file` | `{md5, size, filename, content_type}` |
| GET | `/api/v1/models/{nome}/wallpaper` | C | — | o arquivo |
| DELETE | `/api/v1/models/{nome}/wallpaper` | C (dono do modelo) | — | `204` |

A herança é **por consulta, não por cópia**: a sede que não tem o seu próprio
usa o do modelo, resolvido na hora de servir — trocar no modelo na véspera
chega a todas as sedes já criadas, no boot seguinte. O `wallpaper` do
`GET /config` traz `origin` (`"image"` ou `"model"`) para a tela poder dizer de
onde veio.

`PATCH /api/v1/models/{nome}` aceita `wallpaper_locked`. A ordem das três
regras é o contrato: a trava **da própria imagem** vale sempre (o convite a
fixa de propósito em sedes Livres — wallpaper de patrocinador); a imagem
`unlocked` escapa da trava **do modelo**, como escapa dos campos `locked` do
formulário; senão vale o modelo. Só a administração troca um wallpaper travado
— e só ela liga/desliga o `wallpaper_locked` de uma imagem pelo `PATCH` (o
mesmo portão do `unlocked`).

### Roster e vínculos

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| GET | `/api/v1/site-images/{img}/roster` | C, I, S`roster:read` | — | `{roster:[…], logos:[org_id…]}` |
| PUT | `/api/v1/site-images/{img}/roster` | C, I, S`roster:write` | `{roster:[{user_id, name, display_name, organization, country, seat}]}` | `{ok, entries, kept_bound}`: a lista inteira; **nunca apaga vínculo** (ver abaixo) |
| POST | `/api/v1/site-images/{img}/roster` | C, I, S`roster:write` | `{user_id, name?, display_name?, organization?, country?, seat?}` | `{ok, created, entry}`: acrescenta ou atualiza **um** time pelo `user_id` |
| DELETE | `/api/v1/site-images/{img}/roster/{user_id}` | C, I, S`roster:write` | — | `204` (o vínculo do time, se houver, não é desfeito) |
| GET | `/api/v1/site-images/{img}/roster/logos/{org}?tk=` | C, I, S`roster:read` | — | o arquivo, para a tela (`<img>`); sai com CSP `sandbox` |
| PUT | `/api/v1/site-images/{img}/roster/logos/{org}` | C, I, S`roster:write` | multipart `file` (SVG ou PNG) | `{ok, org_id, format, size}` |
| PUT | `/api/v1/site-images/{img}/machines/{mac}/binding` | C, I, S`bindings:write` | `{user_id}` ou `{name, seat}`, mais `source?`, `at?`, `boot_id?`, `note?`, `create_roster_entry?` | vínculo criado (`roster_entry_created:true` quando criou a entrada) |
| PUT | `/api/v1/site-images/{img}/bindings` | C, I, S`bindings:write` | `{bindings:[{mac, …corpo do vínculo}], create_roster_entry?}` (até 1000) | `{results:[{mac, ok, binding \| code, detail}], bound, failed}` |
| DELETE | `/api/v1/site-images/{img}/machines/{mac}/binding` | C, I, S`bindings:write` | — | `204` |
| GET | `/api/v1/site-images/{img}/machines/{mac}/binding/history?n=` | C, I, S`machines:read` | — | `{history:[{event, at, by, source, …}]}` |
| GET | `/api/v1/site-images/{img}/bindings` | C, I, S`machines:read` | — | `{bindings:[{mac, …}]}` |

O `user_id` do vínculo tem que existir no roster da imagem, senão vem 404
(`code: "user_not_in_roster"`): é o que impede um número de assento virar
vínculo fantasma. Quem publica o vínculo no login e não controla o roster (o
MOJ, com o roster ainda vazio) manda `create_roster_entry`: `true` (os campos do
time vêm do próprio corpo) ou um objeto `{name, display_name, organization,
country, seat}`. É **opt-in**, porque o `user_id` nasce de um User-Agent, que é
entrada do cliente. A entrada criada assim leva `source: "binding"`.

**Escrever o roster nunca apaga um vínculo.** O roster oficial enviado depois
sobrescreve à vontade as entradas `source: "binding"` (e elas perdem a marca);
se ele **omitir** um time que está vinculado a uma máquina, a entrada fica,
marcada, e a resposta do `PUT` lista esses ids em `kept_bound`. `POST …/roster`
e `DELETE …/roster/{user_id}` mexem em **uma** entrada, sob lock: use-os em vez
de ler, modificar e regravar a lista (é corrida com qualquer outro escritor).

`country` é rótulo: recomenda-se ISO alpha-2 (`BR`), alpha-3 passa, e o
servidor só uniformiza a caixa. Nenhuma tela de bloqueio desenha bandeira; o
campo segue para o `lockinfo` e para o relatório.

O **lote** (`PUT …/bindings`) é o vínculo unitário repetido: cada item leva
`mac` e o corpo de sempre, um item ruim não derruba os outros (o resultado vem
por item, com `code`), `create_roster_entry` vale para todos e pode ser
desligado num item, e cada vínculo gravado gera o seu `machine.bound`.

O vínculo gravado tem `bound_at` e `by` (do servidor) e `source` (quem
afirmou: o valor mandado, ou `service:<nome>` para chave de serviço e
`console` para o resto). Todos os instantes são inteiros (epoch em
segundos), como o `t` dos pontos e o `since`/`until` ecoados pelos samples.
`at` do cliente vira `client_at` — o instante do
login no juiz, por exemplo —, `boot_id` diz em qual boot e `note` é texto
livre. Toda mudança vai para o histórico da máquina (`bindings.log`, com
teto): `history` devolve as últimas `n` linhas, `bound` e `unbound`, a
última com o vínculo desfeito. É o que permite ao MOJ publicar o elo no
momento do login e a qualquer consumidor ler `binding` em vez de reconstruir.

> **`GET /bindings` percorre as máquinas CONHECIDAS**, não os vínculos
> gravados: uma máquina passa a existir quando reporta status pela primeira
> vez. Vincular antes disso funciona e fica gravado, mas **não aparece na
> lista** até a máquina bootar. Quem pré-vincula os assentos na véspera vai
> ver `{"bindings": []}` e achar que perdeu o trabalho.

### Máquinas e telemetria

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| POST | `/api/v1/site-images/{img}/machines/{mac}/status` | M | JSON livre da telemetria (teto de 256 kB) | `{pending_commands, lock}` |
| GET | `/api/v1/site-images/{img}/machines?active_since=` | C, I, S`machines:read` | — | `{machines:[…]}` (`active_since`: só quem reportou desde aquele epoch) |
| GET | `/api/v1/site-images/{img}/machines/{mac}` | C, I, S`machines:read` | — | estado completo da máquina |
| GET | `/api/v1/site-images/{img}/seeders` | C, I | — | `{seeders:[{ip, last_seen, ttl_left, released}]}` |
| DELETE | `/api/v1/site-images/{img}/seeders/{ip}` | C, I | libera o seeder: marca `released`; a máquina vê no próximo heartbeat, sai do modo seed e termina o boot | `204` |

Cada máquina devolve `online`, `seconds_since_contact`, `status` (última
telemetria), `binding`, `lock`, `pending`, `logs` e `alerts`, e o que o
servidor deduz do que viu: `boot_id`, `boots` (quantos boots distintos),
`boot_seen_at`, `last_boot` (o instante do boot, mandado pelo agente novo ou
o primeiro contato daquele boot) e `editors_reset_at` (o ack do último
`resetcontaeditores`/`precontest` — é desde então que `editors_time` conta).
O MAC é aceito com `:` ou `-` e normalizado para minúsculas com hífen.

O agente novo manda, além do que sempre mandou, `t_agent` (relógio da
máquina) no topo, `hwinfo.{mac, hostname, dmi_uuid, product_name,
product_vendor, uptime_s, last_boot}`, `sysresources.{psi_mem, psi_cpu,
psi_io, oom_kills, idle_s}` e `operations.editors_time_since`. Tudo
opcional: máquina com agente antigo continua válida.

**Qual agente é este.** A frota é mista (o agente chega por uma camada, sede a
sede), então não adivinhe a versão pela presença de um campo: o agente se
declara no topo do status com `agent_version` (ex.: `"2026.09.2"`) e
`capabilities`, a lista do que ele sabe medir: `psi`, `oom`, `idle`, `skew`
(manda `t_agent`), `editors_since` e `ua_mac` (o User-Agent desta máquina leva
o MAC no fim). Campo ausente num agente que o anuncia quer dizer "não deu para
medir aqui" (kernel sem PSI, sessão sem monitor de ociosidade); sem
`agent_version`, é o agente antigo.

Quando duas máquinas da
sede reportam o mesmo `hwinfo.machine_id`, a segunda ganha um alerta
`identity.duplicate` (com `other_mac`) — home clonada por imagem de disco.

O corpo do `status` é JSON livre de propósito: um coletor novo em
`parts.d/` no cliente entra sem mudança no servidor. Livre não é infinito —
acima de 256 kB a resposta é **413**.

### Logs (journal do kernel e do sistema)

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| POST | `/api/v1/site-images/{img}/machines/{mac}/logs?origem=` | M | `text/plain`, até 1 MiB | `{ok, stored, at}` |
| GET | `/api/v1/site-images/{img}/machines/{mac}/logs?tail=500` | C, I, S`machines:read` | — | `{bytes, journal, acks}` |
| GET | `/api/v1/site-images/{img}/machines/{mac}/samples?since=&until=&limit=` | C, I, S`machines:read` | — | `{mac, points, native_points, resampled, interval_s, since, until, truncated}` |
| GET | `/api/v1/site-images/{img}/samples?since=&until=&limit=&active_since=` | C, I, S`machines:read` | — | NDJSON: uma linha por máquina, no mesmo formato |

Os `points` são a série que o `samples.jsonl` guarda por máquina (uma amostra
por telemetria, a cada 40 a 59 s): `t` epoch (relógio do servidor), `mem` %
de RAM, `ld` load1, `sw` MB de swap, `hd` % do `/home`, `ed` editores abertos
(até 8), `fw` 0/1, `lk` 1 quando a tela está bloqueada — e, quando o agente
manda, `psi_mem`/`psi_cpu`/`psi_io` (pressão, `some avg60`), `oom` (OOM
kills desde o boot), `idle` (segundos sem teclado/mouse), `edm` (minutos
acumulados de editor), `eds` (desde quando `edm` conta) e `skew` (relógio do
servidor menos o do agente, em segundos).

`limit` (1 a 5000, padrão 400) reamostra com passo uniforme mantendo sempre
o primeiro e o último ponto; `resampled` diz se isso aconteceu,
`native_points` quantos pontos a janela tinha e `interval_s` a mediana do
intervalo nativo — sem isso ninguém distingue a cadência do agente do passo
do reamostrador. `truncated` só é verdadeiro quando o teto de 2 MiB do
arquivo cortou de fato e o que sobrou começa depois de `since`. É o que
alimenta os gráficos do duplo clique no hotconfig.

A rota em lote (`/site-images/{img}/samples`) responde `application/x-ndjson`:
uma linha por máquina conhecida, no mesmo formato, gerada máquina a máquina;
`active_since` pula quem não reportou desde aquele instante. Um request por
sede em vez de um por máquina:

```bash
curl -sN "$SERVER/api/v1/site-images/26brbr/samples?since=$SINCE&until=$UNTIL&limit=1000&active_since=$SINCE" \
    -H "Authorization: Bearer $NB3S" | while IFS= read -r linha; do echo "$linha" | jq -c '{mac, n: .native_points}'; done
```

No lote, `limit` vale **por máquina** (cada linha tem até `limit` pontos), e
`truncated` é **de cada linha**: diz que o arquivo daquela máquina foi cortado
pelo teto dentro da janela pedida, não que a resposta HTTP veio incompleta.
`since` e `until` voltam inteiros. A rota comprime quando o cliente pede
(`Accept-Encoding: gzip`, que o `curl --compressed` manda): uma sede de 300
máquinas são vários MB de JSON repetitivo, que encolhem umas dez vezes. É a
única rota que comprime; o SSE e o long-poll não passam por gzip.

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
| POST | `/api/v1/site-images/{img}/machines/{mac}/alerts/{id}/dismiss` | C, I, S`alerts:write` (ou `commands:write`, legado) | — | `{ok, alert}` |
| POST | `/api/v1/site-images/{img}/machines/{mac}/alerts/dismiss-all` | C, I, S`alerts:write` (ou `commands:write`, legado) | — | `{ok, dismissed}` |
| GET | `/api/v1/site-images/{img}/machines/{mac}/alerts/history` | C, I, S`machines:read` | — | `{history:[…]}` datado |

`kind` conhecido: `usb.storage` (pendrive, HD externo), `usb.phone` (MTP/PTP),
`usb.network` (tethering) e `usb.other`. Um `kind` desconhecido **é aceito** —
o cliente pode ganhar um detector novo sem esperar o servidor.

**O alerta fica até alguém dispensar.** Não some quando o dispositivo é
removido: quem espeta um pendrive por cinco segundos não escapa do registro.
Sobrevive a reboot da máquina, a recarga da página e a reinício do servidor
(está em disco). Dispensar grava quem foi e quando, no histórico.

A máquina **não** dispensa o próprio alerta: adulterar o agente não apaga o
rastro. O evento `alert.raised` também vai por webhook, para o MOJ — só para
alerta novo: um evento igual (`kind`, `detail`, `vendor`) a um alerta ainda
aberto da máquina devolve o existente com `repeated: true` e não emite nada.

### Frota: todas as sedes de uma vez

O painel por sede responde "como está a minha sala"; estas duas respondem "o
que está acontecendo no conjunto, e como ajo num recorte dele".

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| GET | `/api/v1/labs` | C | `?dias=7` e `?format=csv` | `{sites:[{id, fullname, machines, active, new, online, locked, alerts, unbound}], days}` |
| POST | `/api/v1/commands` | C | `{command, targets, args?, delay?}` | `{results, machines, failed}` |
| GET | `/api/v1/labs/inventory` | C, S`labs:read` | — | de que é feito o parque: `{machines, processors, ram, sites_hw, editors_now, editors_minutes, disks, disks_low}` |
| GET | `/api/v1/labs/series` | C, S`labs:read` | `?since=&until=&site=` | o histórico da frota (1 ponto/min, com teto de pontos): `{points:[{t, online, mem, cpu, alerts}]}` |

`targets` é `{sede: "all"}` ou `{sede: [macs]}`, misturando os dois à vontade.
Cada sede vira uma entrada em `results` — com `command_id` e `machines`, ou com
`error` e `status`.

Sede marcada `dashboard_hidden` não entra em nenhuma das três leituras.

As rotas de leitura da frota (`/labs`, `/labs/inventory`, `/labs/series`)
aceitam também a **chave de serviço com escopo `labs:read`** — é a chave
compartilhável do dashboard, por `?tk=` na URL ou Bearer. Ela só lê agregados:
não abre hotconfig (o painel exige `machines:read`, que não é concedido) nem
roda comando (as rotas de comando exigem console). A visibilidade respeita os
globs da chave, e os totais são recalculados do subconjunto visível.

`dias` responde **quantas máquinas de cada sede rodaram nos últimos X dias**, e
são dois números porque a pergunta tem duas leituras: `active` é quem teve
contato dentro da janela e `new` é quem foi visto pela PRIMEIRA vez nela. Uma
máquina que apareceu há 40 dias e reportou ontem é ativa e não é nova.

> `first_seen` é quando ESTE servidor viu aquele MAC pela primeira vez, não o
> primeiro boot da máquina na vida: recriar o `data/` reinicia a conta.

`GET /labs` aceita o **cookie sem `X-NB-Console`** — é a exceção da invariante
14, a mesma da prévia do wallpaper e do SSE: o botão de baixar o CSV é um
`<a download>`, e um `<a>` não manda cabeçalho. `POST /commands` **continua
exigindo** o cabeçalho, e a assimetria é o ponto: ler a frota por link é inócuo,
desligá-la não.

O resumo **não devolve o `status` das máquinas**. Ele é livre e pode ter 256 kB;
numa frota de 1890 máquinas seriam ~0,9 MB por atualização, contra dezenas de kB
assim. Para o detalhe de uma sede, use `GET /site-images/{img}/machines`.

`POST /commands` age em várias sedes numa requisição só, em vez de uma por sede
com metade falhando em silêncio. Cada sede entra no relatório com o que
aconteceu, e uma recusada não impede as outras: sede de outro dono responde
`404` ali dentro (não 403 — um 403 confirmaria que o nome existe), e o cadeado
do modelo vale igual, com `403` e o nome do campo.

### Relatório da frota: o perfil nacional e os dados brutos

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| POST | `/api/v1/labs/report` | A | `{dias?, excluir?: [ids]}` | `202` `{status, since, until, excluded, started}` |
| GET | `/api/v1/labs/report` | A | — | `{status, since, until, built_at?, error?, files:[{name,size}]}` |
| GET | `/api/v1/labs/report/{nome}` | A (também por link) | — | o arquivo |

**Só administração.** O artefato é um arquivo único com a frota inteira dentro:
gerá-lo por dono custaria o tempo de máquina por pessoa e abriria caminho para a
sede de alguém entrar no relatório de outro. Sub-admin continua com
`GET /site-images/{img}/report`, que é o mesmo agregado da sede dele e sai na
hora.

A geração é **assíncrona e uma de cada vez**, como a imagem do pendrive: uma
frota de 54 sedes × 35 máquinas com 7 dias de amostra são 1,5 GB lidos, 25
milhões de amostras e ~140 s de CPU (medido). Dentro do worker congelaria o boot de todas as salas, e thread não
resolveria — quem gasta o tempo é `json.loads`, que segura a GIL. Por isso um
subprocesso (`tools/nb3-relatorio-frota`), estado em disco, e a tela
perguntando se ficou pronto.

`status` é `missing`, `building`, `done` ou `failed` (com `error`). Pedir de
novo enquanto uma anda **não é erro**: responde `202` com `started: false`, para
que duas abas abertas não recebam um 409 que ninguém pediu. Um `building` mais
velho que meia hora é tratado como geração morta — se o worker reinicia no meio,
a tarefa vai junto e o estado ficaria travado para sempre.

`excluir` tira sedes do relatório (a de teste inflaria o perfil nacional). Os
ids são validados antes de virarem argumento de subprocesso, e a lista fica em
`excluded` no estado — a tela pré-marca as mesmas sedes na geração seguinte.

Os arquivos, todos de uma passada só (ler 1,5 GB duas vezes seria pagar duas
vezes):

| arquivo | o que é |
|---|---|
| `relatorio.html` | o visual, autocontido: perfil nacional de RAM e processadores, e por sede — máquinas, editores, memória e carga (média e pico), alertas e dmesg |
| `inventario.csv` | uma linha por máquina: sede, MAC, processador, núcleos, RAM, assento, time, organização, país, primeira e última vez vista |
| `editores.csv` | sede, MAC, editor, amostras em que apareceu, minutos acumulados |
| `recursos-hora.csv` | sede, MAC, hora, amostras, memória média e pico, carga média e pico |
| `recursos-brutos.csv.gz` | amostra por amostra: sede, MAC, instante, memória, carga, swap |
| `alertas.csv` | sede, MAC, quando, tipo, detalhe, quem dispensou e quando |
| `resumo.json` | os agregados por sede, os mesmos que o HTML desenha |

O download aceita o **cookie sem `X-NB-Console`**, pelo motivo de sempre: são
`<a download>`. O `{nome}` sai de uma **lista fechada** — é caminho vindo da URL
indo para o disco, e `data/reports/` tem `data/site-images/` de vizinho, com o
token e a chave de máquina de cada sede. Nome fora da lista é `404`.

### Comandos e bloqueio de tela

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| POST | `/api/v1/site-images/{img}/commands` | C, I, S`commands:write` | `{command, target, args?, delay?}` | `{command_id, machines}` |
| GET | `/api/v1/site-images/{img}/commands/{command_id}` | C, I, S`commands:write` | — | `{command_id, command, args, by, created_at, not_before, expires_at, machines, summary:{acked, pending, expired}, targets:[{mac, state, status?, at?, output_bytes?}]}` |
| GET | `/api/v1/site-images/{img}/commands` | C, I, S`commands:write` | — | `{allowed:[…], blocked:{comando: campo}}` |
| GET | `/api/v1/site-images/{img}/machines/{mac}/commands?wait=25` | M | — | `{commands:[…], lock}` (long-poll) |
| POST | `/api/v1/site-images/{img}/machines/{mac}/commands/{cid}/ack` | M | `{status, output?}` | `{ok, found}` |
| POST | `/api/v1/site-images/{img}/lock` | C, I, S`commands:write` | — | trava a TELA de todas as máquinas |
| POST | `/api/v1/site-images/{img}/unlock` | C, I, S`commands:write` | — | destrava a tela de todas |
| POST | `/api/v1/site-images/{img}/machines/{mac}/lock` | C, I, S`commands:write` | — | idem, para uma máquina |
| POST | `/api/v1/site-images/{img}/machines/{mac}/unlock` | C, I, S`commands:write` | — | idem |

> `…/unlock` destrava a **tela de bloqueio**, não o formulário. Campo travado
> do formulário se destrava no modelo (`PATCH …/schema/fields/{chave}`) ou
> marcando a imagem como `unlocked` (`PATCH /api/v1/site-images/{img}`) — são
> coisas diferentes com nomes parecidos, e chamar a errada no meio da prova
> desbloqueia a sala inteira.

`target` é `"all"` ou uma lista de MACs. `delay` adia a execução em segundos.

**Quem executou.** `GET …/commands/{command_id}` responde por máquina:
`acked` (com o `status` que a máquina mandou; `error` também é confirmação),
`pending` (o comando ainda vale e ela não confirmou) ou `expired` (caducou; a
máquina desligada nunca escreve nada, o estado dela se deduz do prazo). O
registro guarda os últimos 500 comandos da sede, por 7 dias; comando anterior a
isso responde `404 command_not_found`. O evento `command.acked` traz
`command_id` e `command` (`id` continua, é o mesmo valor).
Sem `target` o comando vale para **a sala inteira**; por isso um corpo que traz
`macs`, `mac` ou `targets` sem `target` responde **400**: quem mandou um desses
quis escolher máquinas e errou o campo, e obedecer o padrão ali desligaria a
sala toda por engano (o `nb3-api` fez exatamente isso até setembro de 2026).
Um `target` que não seja `"all"` nem lista também é 400.

Uma ordem que nenhuma máquina buscou caduca `command_ttl_sec` segundos
(`data/server.json`, padrão 600) depois do seu `not_before`: é apagada da fila
na leitura seguinte e registrada nos `acks` da máquina com `status: "expired"`.
É o que impede um "desligar" mandado hoje de desligar a máquina que só ligar
amanhã — o alvo `"all"` inclui as máquinas desligadas no momento do envio.
Comandos aceitos: `donottouch`, `cantouch`, `cleanhomenow`, `mlreboot`,
`mlpoweroff`, `disablefirewall`, `enablefirewall`, `resetcontaeditores`,
`precontest`. Qualquer outro valor é recusado com `400`.

`precontest` é a macro do fim do warmup: numa tacada, limpa as homes, trava as
telas, zera a contagem de editores e liga o firewall das máquinas alvo. Além de
enfileirar o comando, o servidor **grava o estado de trava** dessas máquinas —
sem isso a trava que o agente aplica localmente cairia no ciclo seguinte do
long-poll, que obedece o lockstate do servidor. Vale também pela rota da frota
(`POST /api/v1/commands`). Destravar depois é o `unlock` de sempre.

**O cadeado do modelo vale aqui.** Um comando que contradiz um campo `locked`
do formulário é recusado com **403**, dizendo qual campo — `disablefirewall`
com `DISABLE_FIREWALL` travado é o caso que existe hoje. A regra é a mesma do
configureitor (`locked` e não `is_admin` e não `unlocked`), e ela vive num lugar
só de propósito: por um tempo valeu na tela de configuração e não valeu aqui, e
quem não podia desligar o firewall pela primeira desligava pela segunda, na sala
inteira.

Só o sentido permissivo é barrado: `enablefirewall` move a máquina PARA o valor
travado e continua liberado. Chave de serviço conta como "não é administração" —
para deixar um sistema externo desligar o firewall, destrave o campo no modelo.

O `GET` responde o que ESTA credencial pode mandar. A tela do laboratório usa
para não oferecer botão que o servidor vai recusar; quem integra, para não
descobrir apanhando.

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
`command.acked`, `config.updated`, `seeder.joined`, `seeder.released`, `alert.raised`,
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
| GET | `/api/v1/site-images/{img}/usb/image` | C, I, `?tk=` | — | **302** para o `.img.gz` no servidor de arquivos, ou a imagem compactada aqui |
| GET | `/api/v1/usb/generic/image` | C, `?id=&tk=` | — | idem, para a genérica |

**As duas rotas de imagem redirecionam.** Quando a cópia publicada corresponde
à construção atual, elas respondem `302` para o `.img.gz` no
`files.mdp.naquadah.com.br`: são ~206 MB que deixam de sair da máquina que
atende o boot da sala. Use `curl -L`.

Quando não há cópia lá — publicação desligada, envio falhado, ou publicada e
**velha** — elas compactam na hora e transmitem daqui. Nesse caso não há
`Content-Length`, então o download aparece sem porcentagem.

> Publicada e velha é o caso que importa: o arquivo de lá tem a chave de boot
> ANTERIOR, e quem o gravar fica com uma sede que não boota sem nada
> explicando. Por isso `public_url` no estado só é preenchida quando a cópia
> corresponde à construção atual, e `publish_stale` diz quando não corresponde.
> **Não use `public_url` como destino de download** — passe pela rota, que sabe
> escolher.

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

### Relatório da sede por período

| Método | Caminho | Cred. | Resposta |
|---|---|---|---|
| GET | `/api/v1/site-images/{img}/report?since=&until=&format=&lang=` | C, I, S`machines:read` | HTML autocontido (padrão) ou JSON com `format=json` |

`since`/`until` em epoch. `lang` é `pt`, `en` ou `es`. O HTML **não busca nada
de fora** — CSS embutido e gráficos em SVG desenhados pelo servidor —, então
serve para salvar e mandar por mensagem. Aceita `?tk=` na URL além do
cabeçalho, porque é um link que se abre em outra aba.

O conteúdo sai da série temporal que o servidor guarda a cada envio de status
(memória, carga, editores em uso) mais o inventário do último `hwinfo`, os
vínculos com os times, os alertas do período e as estranhezas do `dmesg`.

### Builds de camada por imagem

Além da fila global (`/api/v1/layerbuilds`), a sede constrói a própria camada
de pacotes extras, gastando a cota dela:

| Método | Caminho | Cred. | Corpo | Resposta |
|---|---|---|---|---|
| POST | `/api/v1/site-images/{img}/layerbuilds` | C, I | `{name, packages:[…]}` | job criado + `quota` restante |
| GET | `/api/v1/site-images/{img}/layerbuilds` | C, I | — | `{jobs:[…], quota}` |

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
| GET | `/api/v1/site-images/{img}/webhooks` | A, S`webhooks:write` | — | `{webhooks:[{id, url, secret, events, owner, created_at}]}`, com o segredo mascarado (`***`). A chave de serviço vê só os que ela criou |
| POST | `/api/v1/site-images/{img}/webhooks` | A, S`webhooks:write` | `{url, secret?, events?}` | `201` a entrada com `id` e `created:true`. A mesma `url` pelo mesmo dono atualiza a entrada (`200`, `created:false`, mesmo `id`) em vez de duplicar |
| PUT | `/api/v1/site-images/{img}/webhooks/{id}` | A, S`webhooks:write` | qualquer de `{url, events, secret}` | a entrada. Mandar só `secret` é a rotação do segredo |
| DELETE | `/api/v1/site-images/{img}/webhooks/{id}` | A, S`webhooks:write` | — | `204` |
| POST | `/api/v1/site-images/{img}/webhooks/{id}/test` | A, S`webhooks:write` | — | entrega `webhook.test` agora: `{ok, status_code, error, elapsed_ms, delivery}` |
| GET | `/api/v1/site-images/{img}/webhooks/deliveries?n=` | A, S`webhooks:write` | — | `{deliveries:[…]}`: as entregas que esgotaram as tentativas (`webhooks.log`) |
| PUT | `/api/v1/site-images/{img}/webhooks` | A | `{webhooks:[{id?, url, secret?, events}]}` | `{ok, webhooks, kept}`: a lista inteira, só da administração (ver abaixo) |
| POST | `/api/v1/service-keys` | A | `{name, scopes:[…], images:[globs]}` | `{name, key, scopes, images}` |
| GET | `/api/v1/service-keys` | A | — | lista sem as chaves |
| DELETE | `/api/v1/service-keys/{nome}` | A | — | `204` |

Eventos disponíveis (a lista viva está em `GET /api/v1/events/types`):

| Evento | `data` | Quando |
|---|---|---|
| `machine.first_seen` | `{mac}` | o primeiro contato da máquina |
| `machine.status` | `{mac}` | **a cada telemetria** (dezenas por segundo na frota: não assine sem precisar) |
| `machine.rebooted` | `{mac, boot_id, previous_boot_id, boots, last_boot}` | o `boot_id` mudou (nunca no primeiro contato) |
| `machine.offline` | `{mac, last_seen}` | 90 s sem telemetria; o vigia confere a cada 30 s |
| `machine.online` | `{mac, offline_for}` | voltou a reportar depois de 90 s ou mais fora |
| `machine.locked`, `machine.unlocked` | `{machines:[mac…]}` | trava e destrava |
| `machine.bound`, `machine.unbound` | `{mac, …vínculo}` | vínculo com o time |
| `command.sent` | `{id, command, machines}` | comando enfileirado |
| `command.acked` | `{mac, id, command_id, command, status}` | a máquina confirmou |
| `command.expired` | `{command_id, command, machines:[mac…], count}` | o prazo do comando venceu com máquinas sem confirmar (um evento por comando; melhor esforço: a fonte da verdade é `GET …/commands/{command_id}`) |
| `alert.raised`, `alert.dismissed` | `{mac, id, kind, detail?, vendor?, other_mac?, boot_id, binding}` | `alert.raised` só para alerta NOVO; `binding` é `{user_id}` ou `null` |
| `config.updated` | `{keys:[…]}` | a sede gravou configuração |
| `seeder.joined`, `seeder.released` | `{ip}` | modo seed |

`machine.online` e `machine.rebooted` saem da própria telemetria (do que o
disco lembrava do contato anterior) e sobrevivem a um restart do servidor.
`machine.offline` depende do vigia em memória: depois de um restart o aviso pode
sair atrasado ou repetido, e quem já estava desligado quando o servidor subiu
não é anunciado.

`events` vazio significa "todos os eventos". A URL precisa começar com
`http://` ou `https://`, e cada evento é validado contra o catálogo.

Cada webhook tem um **dono**: `admin`, ou `service:<nome>` quando foi uma chave
de serviço que o criou. A chave de serviço só enxerga e só mexe nos seus (o de
outro dono responde `404 webhook_not_found`), nas imagens do glob dela, com no
máximo 5 por imagem e segredo obrigatório (16 caracteres ou mais). Sub-admin e
token da sede não entram aqui: um webhook é o servidor batendo numa URL
escolhida por quem o configura, de dentro da rede de gestão.

Pelo mesmo motivo, a URL de um webhook de chave de **serviço** precisa ser
`https` para um endereço público. Destino interno só quando a administração o
libera em `data/server.json`
(`{"webhooks": {"allow_hosts": ["moj.interno", "10.1.0.0/16"]}}`); fora disso
vem `400 webhook_url_forbidden`. A conferência roda ao gravar e de novo a cada
entrega. Os webhooks da administração apontam para onde ela quiser.

O **`PUT` da lista inteira** continua existindo para a administração, e foi
feito para o ler-e-regravar não destruir nada: a entrada é casada por `id` e
depois por `url` (e mantém `id`, dono e data); `secret` ausente ou igual à
máscara `***` **mantém o segredo gravado** (`""` limpa); e webhook de chave de
serviço que ficou de fora **não é apagado** (`kept` diz quantos). Para apagar,
use o `DELETE` por `id`.

---

## Cliente de referência (`tools/nb3-api`)

Um arquivo, só biblioteca padrão do Python 3. É para ser **copiado**: quem
integra leva o arquivo e usa, sem venv, sem `pip` e sem depender deste
repositório.

```bash
export NB3_BASE_URL=https://nutellaboot.mdp.naquadah.com.br
export NB3_API_KEY=nb3s_...          # serve nb3a_, nb3s_ e o nb3i_ da sede

nb3-api whoami
nb3-api bulk sedes.tsv > credenciais.csv
nb3-api roster set 26brbr @times.json
nb3-api bind 26brbr 52-54-00-12-34-56 team-001 --seat 012
nb3-api lock 26brbr                  # a sala inteira
nb3-api command 26brbr mlreboot 52-54-00-12-34-56    # só esta máquina
nb3-api command 26brbr cleanhomenow --all            # a sala inteira, por extenso
nb3-api logo 26brbr ufu ufu.png                      # PNG ou SVG
nb3-api machines 26brbr
nb3-api report 26brbr 1785600000 1785700000 > relatorio.html
```

Três coisas nele que valem para qualquer cliente que você escreva:

- **TLS sempre verificado**, sem opção de desligar;
- **falha alto**: resposta fora de 2xx imprime o corpo no stderr e sai != 0. É
  o defeito da invariante 15 — `curl -sS` sem `--fail` devolvia o JSON de erro
  com código de saída **zero**, e dois modelos ficaram vazios com o script
  dizendo que tinha registrado;
- **Bearer, sempre**. O cookie de sessão é do navegador e só vale com o
  cabeçalho `X-NB-Console`; ferramenta usa chave.

Os exemplos em `curl` continuam nas seções abaixo de propósito: eles são a
prova de que a API é HTTP comum, e não depende de cliente nenhum.

## Integração com o MOJ

O MOJ pode tanto **consultar** a API quanto **receber** eventos por webhook.
Os exemplos abaixo usam a sede `26brbr`.

### 1. Criar a chave de serviço

Feito uma vez, pela administração. Os escopos limitam o que a chave faz, e
`images` limita onde ela age.

```bash
curl -sS -X POST https://nutellaboot.mdp.naquadah.com.br/api/v1/service-keys \
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

### 1b. O que a chave dá

A chave se enxerga: `GET /api/v1/whoami` devolve os escopos, os globs crus
(`image_globs`; lista vazia = todas) e as imagens que eles cobrem **agora**
(`images`), e `GET /api/v1/site-images` lista essas imagens com `fullname`,
`country` (quando se sabe) e `machines_total`. É o preflight: prova que a chave
vale, diz que escopo falta sem sondar com 403 e dispensa digitar os ids.
`alerts:write` dispensa alertas sem dar o poder de comando.

`machines:read` lê máquinas, `samples` (por máquina e em lote:
`GET /site-images/{img}/samples?since&until&limit&active_since`, NDJSON) e o
relatório; `bindings:write` publica o elo máquina ↔ time no momento do login:

```bash
curl -sS -X PUT https://nutellaboot.mdp.naquadah.com.br/api/v1/site-images/26brbr/machines/52-54-00-12-34-56/binding \
  -H "Authorization: Bearer $NB3S" -H 'Content-Type: application/json' \
  -d '{"user_id": "team-001", "source": "moj-login", "at": 1788026460, "boot_id": "2172579592"}'
```

### 2. Enviar o roster dos times

```bash
curl -sS -X PUT https://nutellaboot.mdp.naquadah.com.br/api/v1/site-images/26brbr/roster \
  -H "Authorization: Bearer $MOJ_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
        "roster": [
          {
            "user_id": "team-001",
            "name": "Os Batatinhas",
            "display_name": "UnB — Os Batatinhas",
            "organization": {"id": "unb", "name": "Universidade de Brasília"},
            "country": "BR",
            "seat": "012"
          }
        ]
      }'
```

### 3. Enviar o logotipo da instituição

```bash
curl -sS -X PUT \
  https://nutellaboot.mdp.naquadah.com.br/api/v1/site-images/26brbr/roster/logos/unb \
  -H "Authorization: Bearer $MOJ_KEY" \
  -F file=@unb.svg
```

Aceita SVG ou PNG, até 2 MB. O identificador da organização não pode conter
barra nem `..`.

### 4. Vincular o time à máquina

```bash
curl -sS -X PUT \
  https://nutellaboot.mdp.naquadah.com.br/api/v1/site-images/26brbr/machines/52-54-00-12-34-56/binding \
  -H "Authorization: Bearer $MOJ_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "team-001"}'
```

O `user_id` precisa existir no roster da imagem, senão a resposta é `404`
(`code: "user_not_in_roster"`); com `"create_roster_entry": {...}` o vínculo
cria a entrada que faltar (seção "Roster e vínculo"). A partir daí a tela de
bloqueio daquela máquina mostra o nome do time, o logotipo e o lugar.

Na largada (milhares de logins em minutos) e no replay, use o lote: `PUT
…/site-images/<sede>/bindings` com até 1000 itens por pedido.

### 5. Bloquear e desbloquear

```bash
# a sala inteira
curl -sS -X POST https://nutellaboot.mdp.naquadah.com.br/api/v1/site-images/26brbr/lock \
  -H "Authorization: Bearer $MOJ_KEY"

# uma máquina
curl -sS -X POST \
  https://nutellaboot.mdp.naquadah.com.br/api/v1/site-images/26brbr/machines/52-54-00-12-34-56/unlock \
  -H "Authorization: Bearer $MOJ_KEY"
```

Resposta: `{"command_id":"a1b2c3d4e5f6","machines":42,"locked":true}`. As
máquinas recebem em poucos segundos, porque estão penduradas no long-poll.

### 6. Ler telemetria

```bash
curl -sS https://nutellaboot.mdp.naquadah.com.br/api/v1/site-images/26brbr/machines \
  -H "Authorization: Bearer $MOJ_KEY"
```

```json
{"machines": [
  {
    "mac": "52-54-00-12-34-56",
    "online": true,
    "seconds_since_contact": 12,
    "lock": {"locked": false, "since": 1785620000, "by": "moj"},
    "binding": {"user_id": "team-001", "seat": "012", "source": "moj-login", "bound_at": 1785620100, "by": "moj"},
    "pending": 0,
    "boot_id": "2172579592", "boots": 3, "last_boot": 1785619000, "editors_reset_at": 1785620400,
    "status": {
      "t_agent": 1785620500,
      "hwinfo": {"processor": "…", "cores": 8, "memtotal_mb": 15900,
                 "machine_id": "3f2…", "boot_id": "2172579592", "image": "26brbr",
                 "mac": "52-54-00-12-34-56", "dmi_uuid": "…", "product_name": "OptiPlex 3090", "uptime_s": 1500, "last_boot": 1785619000},
      "sysresources": {"mem_pct": 41, "loadavg": [0.6, 0.4, 0.3], "alerts": [], "psi_mem": 0.4, "oom_kills": 0, "idle_s": 12},
      "operations": {"firewall": true, "screen_lock": false, "editors": ["code"],
                     "editors_time": {"code": 40, "total": 42}, "editors_time_since": 1785620400}
    }
  }
]}
```

### 7. Receber eventos por webhook

Com o escopo `webhooks:write`, a própria chave de serviço instala o webhook (e
reinstalar com a mesma URL não duplica):

```bash
curl -sS -X POST https://nutellaboot.mdp.naquadah.com.br/api/v1/site-images/26brbr/webhooks \
  -H "Authorization: Bearer $NB3S" -H 'Content-Type: application/json' \
  -d '{"url": "https://moj.naquadah.com.br/hooks/nutellaboot?contest=c1",
       "secret": "um-segredo-de-16-caracteres-ou-mais",
       "events": ["alert.raised", "alert.dismissed"]}'
```

Ou pela administração, com a lista inteira:

```bash
curl -sS -X PUT https://nutellaboot.mdp.naquadah.com.br/api/v1/site-images/26brbr/webhooks \
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
  "at": 1785620123,
  "delivery": "5f0c1d6e2a7b4c1e9d3f8a6b7c5d4e3f",
  "data": {"machines": ["52-54-00-12-34-56"]}
}
```

`at` é o instante do **evento**, inteiro. `delivery` identifica a entrega e vai
dentro do corpo (logo, dentro da assinatura): é o mesmo nas três tentativas,
assim como o corpo inteiro, byte a byte. **Deduplique por `delivery`**: uma
tentativa repetida é a mesma entrega cuja resposta se perdeu, não um evento
novo. Cada assinante tem o seu `delivery`.

| Cabeçalho | Conteúdo |
|---|---|
| `X-NB-Signature` | `sha256=<HMAC-SHA256 do corpo cru, com o segredo>` (só quando há segredo) |
| `X-NB-Delivery` | o mesmo `delivery` do corpo (o do corpo é o assinado) |
| `X-NB-Attempt` | `1`, `2` ou `3` |
| `X-NB-Event` | o nome do evento |
| `X-NB-Webhook-Id` | o `id` do webhook que recebeu, quando ele tem um |
| `User-Agent` | `NutellaBoot3/<versão>` |

Verificação no lado do MOJ:

```python
import hashlib
import hmac

def assinatura_confere(corpo: bytes, cabecalho: str, segredo: str) -> bool:
    """corpo = bytes crus da requisição, ANTES de qualquer parse."""
    esperado = "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, cabecalho or "")
```

A entrega é de melhor esforço: até três tentativas (espera de 1 s e 2 s entre
elas), tempo limite de 5 segundos cada, sem seguir redirecionamento. Um webhook
lento nunca segura o boot nem o comando de bloqueio: o envio acontece em segundo
plano, com no máximo 8 entregas simultâneas. A entrega que esgota as tentativas
fica registrada em `webhooks.log` da imagem (evento, `delivery`, host, caminho e
o último status; nunca o corpo, o segredo ou a query string).

**Liste os eventos que você quer.** `events: []` assina tudo, inclusive
`machine.status`, que dispara a cada telemetria de cada máquina (dezenas por
segundo na frota inteira).

---

## Códigos de erro

| Código | Quando |
|---|---|
| `400` | dados inválidos (comando fora da lista, MAC malformado, campo desconhecido, pacote com nome suspeito) |
| `401` | credencial ausente, inválida ou chave de boot errada |
| `403` | credencial válida sem escopo suficiente, ou sem acesso àquela imagem |
| `404` | imagem, modelo, job ou recurso inexistente |
| `413` | arquivo grande demais (wallpaper acima de 12 MB, logotipo acima de 2 MB) |

| `429` | muitas tentativas; o cabeçalho `Retry-After` diz em quantos segundos tentar de novo |

O corpo do erro é `{"detail": "mensagem em português", "code": "codigo_estavel"}`.
**Decida pelo `code`, nunca pelo texto de `detail`** (a frase pode mudar) nem só
pelo status: um `404` do vínculo pode ser `user_not_in_roster` ou
`image_not_found`, e são providências diferentes. Erro que não tem código
próprio leva o padrão do status. O catálogo vivo está em
`GET /api/v1/events/types` (`error_codes`).

| `code` | Status | Quando |
|---|---|---|
| `unauthorized` | 401 | credencial ausente ou inválida |
| `insufficient_scope` | 403 | a chave de serviço não tem o escopo que a rota pede |
| `image_out_of_scope` | 403 | a imagem existe, mas está fora dos globs da chave de serviço |
| `image_not_found` | 404 | a site-image não existe (para o console, também a que é de outro dono) |
| `user_not_in_roster` | 404 | o `user_id` do vínculo não está no roster da imagem |
| `invalid_mac` | 400 | MAC fora do formato `aa-bb-cc-dd-ee-ff` |
| `command_not_allowed` | 400 | comando fora da lista |
| `command_blocked` | 403 | comando bloqueado pelo cadeado do modelo |
| `no_target` | 400 | nenhuma máquina alvo, ou `target` malformado |
| `rate_limited` | 429 | veja `Retry-After` |
| `bad_request`, `forbidden`, `not_found`, `conflict`, `payload_too_large`, `validation_error` | 400, 403, 404, 409, 413, 422 | os padrões do status, para o erro sem código próprio (`validation_error` traz `detail` como lista) |
