# Manual de operação

Este é o documento do dia a dia: preparar o serviço, criar imagens, entregar a
configuração para as pessoas e conduzir uma sessão (uma prova, um laboratório,
uma sala gerenciada). O NutellaBoot 3 é uma ferramenta de gestão de
laboratórios com boot em rede; a Maratona SBC de Programação é o uso de origem
e aparece aqui como exemplo, não como o único cenário.

Todos os comandos assumem que você está na raiz do repositório
(`nutellaboot3/`). Onde precisa de `sudo`, está dito por quê.

## 1. Preparar o serviço

Isso se faz uma vez por temporada, quando sai a nova imagem base do sistema
(no caso da maratona, o Maratona Linux do ano). O caminho inteiro, do arquivo
`.raw` até uma máquina bootando:

```
imagem-mestre .raw  (dezenas de GB)
   │
   │  1.1  sudo nb3-gerar-squash --raw ... --name ... --publish
   ▼
camada base .squash  em data/blobs/  e no servidor de arquivos
   │
   │  1.2  nb3-nova-temporada --de <ano passado> --para <ano> --base <arquivo>
   ▼
MODELO da temporada  (base nova + telemetria, wifi e extras herdados)
   │
   │  1.3  nb3-camada-telemetria --model <ano> --publish    (se o agente mudou)
   │  2.   criar a site-image de cada sede a partir do modelo
   ▼
SITE-IMAGE  →  GET /boot/v3/<sede>/manifest  →  a máquina baixa e monta
```

### As camadas e seus papéis

Cada camada diz o que é. Isso não é enfeite: é o que faz trocar a base
substituir a certa, já que o nome do arquivo muda a cada temporada.

| Papel | O que é | Onde fica na lista |
|---|---|---|
| `base` | o sistema operacional inteiro | **por último** |
| `telemetry` | agente, tela de bloqueio, detecção de USB | na frente |
| `wifi` | perfis de rede sem fio | na frente |
| `extra` | pacotes, navegador, licenças, wallpaper | na frente |

**A ordem é a prioridade no overlay: a primeira ganha.** A base fica por
último justamente para perder para todas as personalizações — inverter faz o
sistema base sobrescrever tudo, em silêncio.

> Se você tem modelos de antes desta convenção, rode
> `tools/nb3-migrate-roles --dry-run` e depois sem a flag. Ele deduz o papel
> pelo nome do arquivo e pela posição, mostrando o antes/depois.

### 1.1 Gerar a camada base

Transforma a imagem-mestre num `.squash`:

```bash
sudo -E NB3_ADMIN_KEY=nb3a_... NB3_BASE_URL=https://nutellaboot.naquadah.com.br \
    tools/nb3-gerar-squash \
        --raw /caminho/ubuntu-24.04-initial.raw \
        --name maratonalinux2026 \
        --publish
```

**Por que sudo:** o comando precisa de `losetup` e `mount` para abrir a
partição raiz de dentro do `.raw`. É o único motivo — todo o resto do fluxo
roda como usuário comum.

Demora bastante (dezenas de GB). No fim ele imprime o caminho, o md5 e o
tamanho, e diz qual é o comando seguinte.

**Use `--publish`.** Sem ele a camada fica marcada para ser baixada da própria
máquina de gestão — para a base, isso é a sala inteira puxando vários GB do
mesmo servidor que responde à API durante a prova. Com `--publish`, o arquivo
vai para o servidor de arquivos e é de lá que as máquinas baixam.

O `--register <modelo>` registra direto num modelo que já existe, trocando a
base dele. Para começar a temporada, prefira o passo seguinte.

### 1.2 Criar o modelo da temporada

O **modelo** é o conjunto de camadas mais o formulário que as sedes preenchem.
Toda site-image deriva de um.

Um comando faz a temporada inteira — duplica o modelo do ano passado
(herdando telemetria, wifi, extras **e os cadeados do formulário**) e troca só
a base:

```bash
export NB3_BASE_URL=https://nutellaboot.naquadah.com.br
export NB3_ADMIN_KEY=nb3a_...

# sempre veja antes o que vai acontecer
tools/nb3-nova-temporada --de maratonalinux2404 --para maratona2026 \
    --base data/blobs/maratonalinux2026.squash-2026-08-02-12-36 --dry-run

# e então, de verdade
tools/nb3-nova-temporada --de maratonalinux2404 --para maratona2026 \
    --base data/blobs/maratonalinux2026.squash-2026-08-02-12-36 --publish
```

Ele imprime as camadas antes e depois, e confere no fim que sobrou **uma**
base. O modelo do ano anterior **não é tocado**: as sedes que ainda usam
aquele modelo seguem bootando o que bootam hoje.

Casos que ele trata:

- **primeira temporada** (não há modelo anterior): omita `--de`. Nasce só com
  a base; a telemetria entra no passo 1.3.
- **o modelo de destino já existe e está vazio** (resultado típico de um
  registro que falhou): as camadas e os cadeados do `--de` são copiados, e só
  então a base é trocada.
- **regerar a base e registrar de novo**: continua com uma base só.

Também dá para fazer pela tela, em `/admin/` → **Modelos** → *Partir de* — mas
aí a camada base tem que ser adicionada à mão, com o md5 do arquivo.

### Conferir que colou

Este passo não é opcional. Até esta versão, um erro de digitação no nome do
modelo fazia o registro falhar **em silêncio** (o `curl` devolvia código de
sucesso num 404), e dava para terminar achando que registrou:

```bash
curl "$SERVER/api/v1/models/maratona2026" -H "Authorization: Bearer $ADMIN" |
    python3 -m json.tool | grep -E '"file"|"role"'
```

Tem que aparecer a base nova, com `"role": "base"`, por último. Se a lista vier
vazia, o registro não aconteceu — confira o nome do modelo em
`GET /api/v1/models`.

### 1.3 Embarcar a telemetria

O agente, a tela de bloqueio e a regra que detecta pendrive moram em
`client/telemetry/`, já no layout final do sistema de arquivos. Um comando os
transforma em camada, publica e registra no modelo:

```bash
export NB3_BASE_URL=https://nutellaboot.naquadah.com.br
export NB3_ADMIN_KEY=nb3a_...

tools/nb3-camada-telemetria --dry-run                       # ver antes
tools/nb3-camada-telemetria --model maratonalinux2604 --publish
```

Não precisa de root: o `-all-root` do `mksquashfs` grava tudo como `root:root`
sem privilégio nenhum.

O comando **remove do modelo a camada de telemetria anterior**. Sem isso, duas
versões do agente disputariam `/usr/share/mlog/agent.sh` e a primeira da lista
venceria em silêncio. Use `--manter-antiga` se quiser as duas (raramente é o
que se quer).

A camada entra na **posição 0**, na frente do sistema base — é a regra do
overlay: a primeira ganha.

Rode este comando toda vez que mexer em `client/telemetry/`. As máquinas pegam
a versão nova no próximo boot; nada precisa ser feito nelas.

### 1.4 Gerar o kernel e o initrd

```bash
sudo tools/nb3-build-initrd --raw /caminho/ubuntu-24.04-initial.raw
# resultado em client/build/{vmlinuz,initrd.img}
```

**Por que sudo:** o `initramfs-tools` roda *dentro* da imagem-mestre — é
`losetup` + `mount` + `chroot`.

Se preferir não dar root no servidor, dá para fazer o mesmo dentro de uma
máquina virtual: suba a imagem-mestre, copie `client/initramfs-tools/` para
`/etc/initramfs-tools/`, rode `update-initramfs -c -k <versão>` e traga
`vmlinuz` e `initrd.img` de volta para `client/build/`. O resultado é idêntico.

### 1.5 Gravar o pendrive

**Pela tela, que é o caminho normal.** Criar uma sede já dispara a geração, e o
cartão de credenciais mostra o link assim que fica pronto (uns 40 segundos). O
mesmo aparece no `/admin/`, na seção **Pendrive de boot**, e no configureitor —
que é a tela que a sede recebe.

São três downloads, e a ordem é de propósito:

| O quê | Tamanho | Para quê |
|---|---|---|
| imagem do pendrive | ~400 MB | **a mesma para todas as sedes** |
| `nutellaboot.conf` | ~500 B | a sala, a chave de boot e o servidor |
| imagem já configurada | ~400 MB | alternativa: nada para editar, só serve nesta sala |

O caminho recomendado é o primeiro: grave a imagem uma vez, copie o
`nutellaboot.conf` para dentro do pendrive (é uma partição FAT comum, abre em
qualquer computador) e pronto. Foi para isso que o pendrive genérico existe —
no NutellaBoot 2 eram ~45 imagens de 400 MB que só diferiam nesse arquivo.

A imagem já configurada existe para quem prefere não abrir arquivo nenhum. Ela
leva a chave de boot dentro, então o nome tem um sufixo aleatório
(`26brbr-7f3a9c21.img`) — sem isso, quem adivinhasse `26brbr.img` no servidor
de arquivos levaria a chave da sala junto.

**Quando a chave de boot é rotacionada** (ou o initrd é reconstruído), as três
telas passam a mostrar *desatualizada*, com o motivo e um botão de regerar.
Nada é regerado sozinho: todo pendrive já gravado vai ter que ser regravado de
qualquer jeito, e quem rotacionou decide quando.

**Por linha de comando**, o mesmo gerador:

```bash
# pendrive genérico: a sede é escolhida editando o arquivo na partição
tools/nb3-genusb --output maratona2026.img

# pendrive já apontado para uma sede, com a chave de boot buscada na API
NB3_ADMIN_KEY=nb3a_... tools/nb3-genusb \
    --output 26brbr.img \
    --imageroot 26brbr \
    --fetch-key \
    --server https://nutellaboot.naquadah.com.br \
    --wifi minhas-redes.conf
```

Sem `--wifi`, o `wifi.conf` embarcado vem só com os comentários explicando o
formato — as redes de exemplo **não** vão junto, porque a imagem genérica é
publicada num diretório público.

> **Atenção ao `--imageroot`:** ele fixa a sede também na linha de comando do
> GRUB, que vence o `nutellaboot.conf`. Num pendrive gravado assim, editar o
> arquivo não troca a sala — é preciso editar o `grub.cfg`, que também está na
> partição.

**Não precisa de sudo**: a imagem é montada manipulando o arquivo
(`sfdisk`/`mtools` + `grub-mkstandalone`), sem `losetup` nem `mount`.

Para gravar no pendrive físico, aí sim:

```bash
sudo dd if=maratona2026.img of=/dev/sdX bs=4M status=progress oflag=sync
```

**O que vem do servidor de arquivos vem compactado** (400 MB viram ~205), então
o comando é outro — e mandar `dd` num `.gz` grava o arquivo compactado no
pendrive, que não boota e não diz por quê:

```bash
zcat maratona2026.img.gz | sudo dd of=/dev/sdX bs=4M status=progress oflag=sync
```

As telas mostram o comando certo para o link que oferecem; esta seção é para
quem baixou o arquivo na mão.

Depois de gravado, o pendrive é uma partição FAT normal: monte em qualquer
computador e edite `nutellaboot.conf` (sede, chave de boot) e `wifi.conf`
(redes) com um editor de texto.

### 1.6 Publicação de arquivos (files.mdp)

Camadas têm vários GB e imagens de pendrive têm centenas de MB. Servir isso
pela máquina de gestão significa uma sala inteira baixando do mesmo servidor
que responde à API no meio da prova. Por isso esses arquivos são enviados para
um **servidor de arquivos**, e o manifest entregue às máquinas passa a apontar
para a URL pública de lá.

A configuração fica no bloco `publish` do `data/server.json`:

```json
{
  "publish": {
    "enabled": true,
    "host": "files.mdp.naquadah.com.br",
    "user": "root",
    "paths": {
      "layers": "/var/www/html/maratonalinux",
      "usb": "/var/www/html/mlbootimages"
    },
    "base_urls": {
      "layers": "https://files.mdp.naquadah.com.br/maratonalinux",
      "usb": "https://files.mdp.naquadah.com.br/mlbootimages"
    }
  }
}
```

O envio é feito com `rsync` sobre SSH, sem interação: o usuário que roda o
servidor na máquina de gestão precisa ter **chave SSH autorizada** no `root`
do files.mdp. Confira com:

```bash
ssh -o BatchMode=yes root@files.mdp.naquadah.com.br 'echo ok'
```

Se a publicação estiver **desligada** (`enabled: false`), nada é enviado e as
máquinas baixam da própria máquina de gestão — funciona, mas não é o que você
quer numa sede grande.

**O painel Publicação**, no `/admin/`, lista cada arquivo com o estado
(publicado, falhou, desligado) e a URL ou o motivo do erro. Quando o servidor
de arquivos está fora do ar na hora da construção, a camada fica marcada como
falha e continua sendo servida pela máquina de gestão — o boot não quebra. Use
**"Reenviar pendentes"** quando o servidor voltar; ele reenvia tudo que não
está publicado.

Para publicar a imagem de pendrive junto com a geração:

```bash
tools/nb3-genusb --output 26brbr.img --imageroot 26brbr --publish
```

Ele copia a imagem para `data/usb/` (para o botão de reenviar saber onde
encontrá-la) e envia para o diretório configurado em `paths.usb`.

Trocar o files.mdp por uma CDN no futuro é editar `base_urls` — nenhum outro
lugar do sistema sabe o nome do servidor.

## 2. Criar imagens

Uma **imagem** é um sistema que as máquinas de uma sala baixam ao ligar. Há
três formas de criar: a administração cria uma a uma ou em massa; e pessoas de
fora criam a própria imagem com um **código de convite** — sem passar por você
a cada vez.

### Namespace reservado

Nomes que **começam com dígito** são reservados à administração. É a convenção
usada em eventos — na maratona, o ano na frente: `26brbr`, `26spsp`, `26mgbh`.
O servidor marca essas imagens como `contest`; as demais (`ifsp`, `unb-apc`,
`curso-algoritmos`) ficam como `personal`, e são as que professores e
instituições criam ou recebem.

A regra está em `data/server.json` (`reserved_prefix_regex`, padrão `^[0-9]`).
Só quem tem chave de administração cria nomes reservados; a criação por convite
recusa qualquer nome que comece com dígito. O namespace deixa claro, na
listagem, o que é oficial e o que é de terceiros.

### Uma de cada vez

Abra `/admin/` no navegador, informe a chave de administração e preencha
identificador, nome e modelo. A tela devolve, **uma única vez**, o token, a
chave de máquina, a chave de boot e o link de configuração. Copie tudo antes de
sair da página.

No mesmo formulário dá para já enviar o **papel de parede** da imagem (PNG ou
JPEG) e marcar **"não deixar trocar o papel de parede"**. Marcando essa caixa,
o papel de parede fica travado: só a administração muda. No configureitor a
pessoa continua vendo o papel de parede atual, mas os botões de enviar e
remover ficam desabilitados, com a mensagem de que o papel de parede foi
definido pela organização.

O envio é feito logo depois de criar a imagem, então uma falha no upload não
impede a criação — a imagem já existe e você pode enviar o arquivo depois pelo
configureitor.

Se preferir travar (ou destravar) o papel de parede de uma imagem que já
existe, use a API:

```bash
curl -X PATCH https://nutellaboot.naquadah.com.br/api/v1/site-images/26spsp \
    -H "Authorization: Bearer $NB3_ADMIN_KEY" \
    -H 'Content-Type: application/json' \
    -d '{"wallpaper_locked": true}'
```

Os **códigos de convite** também podem fixar isso: ao gerar um código com
`wallpaper_locked`, todas as imagens criadas com ele já nascem com o papel de
parede travado.

### Em massa

No começo da temporada são mais de 50 sedes. Monte um arquivo separado por TAB:

`sedes-2026.tsv`
```
26brbr	Brazilian Finals	maratonalinux2604
26spsp	SEDE: SP, São Paulo	maratonalinux2604
26mgbh	SEDE: MG, Belo Horizonte	maratonalinux2604
```

```bash
export NB3_ADMIN_KEY=nb3a_...
tools/nb3-bulk-create sedes-2026.tsv > credenciais-2026.csv
chmod 600 credenciais-2026.csv
```

O CSV de saída tem uma linha por sede com `id, ok, token, machine_key,
configureitor_url, error`. Linhas inválidas não impedem as outras: cada uma é
tratada de forma independente e o erro aparece na sua própria linha.

Guarde esse arquivo com cuidado — é a única cópia em claro dos tokens.

### Migrar do NutellaBoot 2

```bash
tools/nb3-import-nb2 --dry-run          # mostra o que vai fazer
tools/nb3-import-nb2                    # importa de verdade
tools/nb3-import-nb2 --glob '25br*'     # só um subconjunto
tools/nb3-migrate-roles --dry-run       # confira o papel deduzido de cada camada
tools/nb3-migrate-roles                 # e grave
```

**O `nb3-migrate-roles` não é opcional aqui.** O NutellaBoot 2 não tinha papel
de camada; sem ele, a troca de base da temporada seguinte não reconhece a base
importada, deixa as duas no modelo, e a máquina monta duas raízes sobrepostas
sem erro em lugar nenhum. Importações feitas a partir desta versão já saem com
papel — o comando existe para as anteriores. O `nb3-nova-temporada` e o
`nb3-gerar-squash --register` recusam modelo com camada sem papel.

Ele converte nome, modelo (inclusive detectando o perfil desbloqueado),
valores de configuração, camadas extras e o wallpaper — se o arquivo estiver na
cópia local do site. Tokens e senhas antigas **não** são importados: a senha de
seeder do nb2 era `md5("qwer <sede>")`, derivável por qualquer pessoa. Cada
imagem recebe credenciais novas, exportadas em CSV.

### Deixar outras pessoas criarem a própria imagem

Nem toda imagem precisa passar por você. Um professor, um laboratório ou uma
instituição pode criar a própria imagem com um **código de convite**. O código
é a credencial: quem o recebe cria sozinho, dentro de uma cota que você define.

**Passo 1 — marque ao menos um modelo como público.** Só modelos públicos
podem ser usados na criação por convite (os modelos de prova bloqueados ficam
privados, fora do alcance de terceiros). No `/admin/`, na seção de Modelos,
clique em "Tornar público". Ou pela API:

```bash
curl -X PATCH "$SERVER/api/v1/models/generico" \
    -H "Authorization: Bearer $NB3_ADMIN_KEY" \
    -H 'Content-Type: application/json' \
    -d '{"public": true, "description": "Ubuntu genérico para laboratórios"}'
```

**Passo 2 — gere os códigos e entregue.** No `/admin/`, na seção **Convites**,
escolha quantos códigos, quantas imagens cada um permite e a cota de camadas
por imagem, e clique em gerar. Ou pela API:

```bash
curl -X POST "$SERVER/api/v1/invites" \
    -H "Authorization: Bearer $NB3_ADMIN_KEY" \
    -H 'Content-Type: application/json' \
    -d '{"count": 10, "max_images": 1, "max_models": 2, "build_quota": 5,
         "label": "Laboratório de Computação da UFXX"}'
```

Cada código sai no formato `NB3-XXXX-XXXX-XXXX`. Os campos: `count` (quantos
códigos gerar), `max_images` (quantas site-images o código cria, padrão 1),
`max_models` (quantos modelos próprios, padrão 2), `build_quota` (quantas
camadas de pacotes, padrão 5), `label` (nome amigável que aparece no console
de quem recebe), `model` (opcional — fixa o modelo, senão a pessoa escolhe
entre os públicos) e `expires_at` (opcional, epoch). Entregue o código por um
canal privado.

**O código é credencial de longa duração**, não um bilhete de uso único: é
com ele que a pessoa volta ao console (veja a seção seguinte). Por isso os
códigos novos têm três grupos (60 bits) em vez de dois; os antigos, de dois
grupos, continuam valendo.

**Passo 3 — a pessoa cria.** Ela abre `/criar/`, na aba "Tenho um código de
convite", cola o código, escolhe um nome (que **não** pode começar com dígito),
um nome de exibição e o modelo público. Ao criar, a tela devolve — **uma
única vez** — o token, a chave de boot, a chave de máquina e os links prontos do
configureitor e do painel. A partir daí ela cuida da própria imagem, e pode até
instalar pacotes extras (ver [layer-builds.md](layer-builds.md)), dentro da
cota do código.

**Passo 4 — a pessoa volta.** O mesmo código abre um **console de
sub-administração** em `/admin/`: a mesma tela que você usa, mostrando só o
que é dela. Lá ela cria modelos próprios (partindo dos públicos), deriva
outras site-images dentro da cota, monta camadas e vê as credenciais das
imagens dela. Não vê convites, pedidos, publicação nem criação em massa, e não
cria nome começando por dígito nem nome reservado.

Para revisar ou revogar códigos, use a lista na seção Convites do `/admin/` (o
botão "Revogar") ou `DELETE /api/v1/invites/<código>`. **Atenção:** revogar
tira o console de quem já criou coisas. Se o convite tiver objetos, a API
responde 409 dizendo o que ficaria órfão e só apaga com `?force=true`. Para
apenas tirar o acesso sem perder o histórico, prefira suspender:

```bash
curl -X POST "$SERVER/api/v1/owners/invite:NB3-XXXX-XXXX-XXXX/disable" \
     -H "Authorization: Bearer $NB3_ADMIN_KEY" \
     -H 'Content-Type: application/json' -d '{"disabled": true}'
```

Para ver quem são os sub-admins, quanto já usaram e aumentar a cota de alguém
sem emitir um convite novo (que criaria uma segunda identidade e espalharia os
objetos entre as duas):

```bash
curl "$SERVER/api/v1/owners" -H "Authorization: Bearer $NB3_ADMIN_KEY"

curl -X PATCH "$SERVER/api/v1/owners/invite:NB3-XXXX-XXXX-XXXX/quotas" \
     -H "Authorization: Bearer $NB3_ADMIN_KEY" \
     -H 'Content-Type: application/json' -d '{"max_images": 5, "max_models": 3}'
```

### Fila de pedidos (para quem não tem código)

Quem não recebeu um código pode pedir acesso. Na aba "Não tenho código" de
`/criar/`, a pessoa informa o nome desejado, um contato e uma justificativa. O
pedido cai na fila.

No `/admin/`, a seção **Pedidos** lista os pendentes. Em cada um você:

- **Aprova enviando um código** — o servidor gera um convite e você repassa o
  código para o contato informado; ou
- **Recusa**.

Pela API, os pedidos ficam em `GET /api/v1/requests`, e a decisão é
`POST /api/v1/requests/<id>/approve` (com `{"action":"issue_code"}` para emitir
um código, ou os campos da imagem para criar direto) ou
`POST /api/v1/requests/<id>/reject`.

### Conter abuso

A criação por convite é aberta à internet, então vale saber como ela se
protege — e um ajuste de proxy que você precisa garantir.

- **Sem código, não cria.** A rota pública de criação exige um código válido;
  não há criação anônima.
- **Cota por código e por imagem.** O código esgota depois de `max_images`
  criações; cada imagem criada só constrói `build_quota` camadas de pacotes.
  Estourou, a pessoa pede à administração para aumentar (ou você gera outro
  código).
- **Namespace reservado.** Nomes começando com dígito são recusados para quem
  entra por convite — em `/criar/` e também no console de sub-administração.
  O mesmo vale para a lista de nomes da casa (`maratona`, `icpc`, `sbc`,
  `admin`, …), configurável em `reserved_names` no `data/server.json`.
- **Isolamento por dono.** Cada modelo e cada site-image guarda quem criou. O
  que é de outro dono responde **404** para um sub-admin, não 403 — um 403
  confirmaria que o nome está tomado, e nomes são livres por ordem de chegada.
- **Erro de código limitado por IP.** Tentativa repetida de credencial de
  console leva 429; sem isso, adivinhar um código seria só questão de tempo de
  CPU alheio.
- **Modelos públicos, só os marcados.** Quem é de fora nunca parte de um
  modelo de prova bloqueado.
- **Limite de taxa por IP.** As rotas públicas (`/api/v1/public/site-images` e
  `/api/v1/public/requests`) têm um limite por IP; uma rajada leva `429`.

> **Ressalva importante de operação.** O limite de taxa enxerga o IP de quem
> chega ao servidor. Atrás do proxy, esse IP é o do próprio proxy
> (`127.0.0.1`), e o limite passaria a ser global em vez de por IP. Para o
> limite funcionar de verdade, o nginx precisa repassar o IP real:
>
> ```nginx
> location / {
>     proxy_pass http://127.0.0.1:8890;
>     proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
> }
> ```
>
> O servidor usa o primeiro endereço de `X-Forwarded-For` como chave do limite.

## 3. Entregar a configuração para as pessoas

### Entrar no console

Informe a chave uma vez, em `/admin/` (ou na caixa de administração da página
inicial). A partir daí o navegador guarda uma **sessão de 30 dias**:
recarregar a página, abrir outra aba ou voltar no dia seguinte não pedem a
chave de novo. A chave em si não fica guardada no navegador — o que fica é um
cookie que nenhum script da página consegue ler.

O mesmo vale para quem entra com código de convite: o código abre a sessão do
console de sub-administração.

**Sair** encerra a sessão daquele navegador. Se uma máquina se perdeu com a
sessão aberta, dá para derrubar todas de uma vez:

```bash
curl -X DELETE "$SERVER/api/v1/session?all=true" \
    -H 'X-NB-Console: 1' -b cookies.txt
```

E, como último recurso, **trocar a chave de administração derruba todas as
sessões abertas com ela** — a identidade é reconferida a cada requisição.

> Se você usava a versão anterior e a tela pedia a chave a cada recarregamento,
> era um defeito: o console regravava o campo de login (vazio no carregamento)
> por cima da chave guardada. Não é mais preciso contornar isso.

### A página inicial

O endereço raiz do servidor (`https://nutellaboot.naquadah.com.br/`) é a porta
de entrada para todo mundo, em português, inglês e espanhol. Ela tem quatro
cartões: **coordenador** (cola o identificador e o token de uma imagem que já
existe e abre a configuração ou o painel), **quero uma imagem própria** (leva
para `/criar/`), **administração** (cola a chave de admin e entra em `/admin/`)
e **documentação**. É para lá que você manda as pessoas.

### Pegar o token e o link de uma imagem

O jeito fácil: em `/admin/`, na lista de imagens, clique em **"ver credenciais
e link"** na linha da imagem. Aparece um cartão com o token, a chave de boot, a
chave de máquina e os links prontos do configureitor e do hotconfig — cada um
com um botão de copiar. Isso **não** rotaciona nada, então os links já
distribuídos continuam válidos.

Cada imagem tem um link próprio, já com o token embutido:

```
https://nutellaboot.naquadah.com.br/configureitor/?id=26spsp&tk=nb3i_...
```

Esse link **é** a credencial: quem tem o link configura a imagem. Mande por
canal privado. Se vazar, gere outro em `/admin/` ("Gerar novo token") — aí os
links antigos param de funcionar e você distribui o novo.

Todas as páginas funcionam em português, inglês e espanhol — o idioma é
detectado pelo navegador e pode ser trocado no canto superior direito.

### O que a pessoa pode configurar

| Campo | O que faz |
|---|---|
| Login automático | entra direto no usuário `icpc` (pode ser bloqueado pela organização) |
| Limpar a home a cada boot | apaga os arquivos do usuário a cada partida |
| Fuso horário | fuso das máquinas da sede |
| Layouts de teclado | ordem dos layouts; o primeiro é o padrão |
| Idioma das telas | idioma das mensagens na máquina, incluindo a tela de bloqueio |
| Semear a imagem (P2P) | esta máquina serve a imagem para as outras da rede |
| RAM mínima | mínimo para bootar (bloqueado) |
| Firewall / liberados | política de rede da prova (bloqueado) |
| Página inicial do navegador | endereço do juiz, MOJ ou BOCA (bloqueado) |
| Permitir pendrives / VM / mexer na rede | permissões dos competidores (bloqueados) |
| Tema da tela de bloqueio | clássico, animado ou minimalista |
| Senha para destravar a tela | senha local de emergência |

Campos marcados como **bloqueados** aparecem em cinza com a etiqueta "Definido
pela organização": são as decisões que não podem variar por sala (numa prova,
por exemplo, o firewall e as permissões).

### Escolher o que a sede pode mudar

Quais campos ficam bloqueados é decisão sua, e se ajusta pela tela. No
`/admin/`, na seção do modelo, **clique no nome do modelo**: abre a lista de
todos os campos daquele modelo, cada um com um cadeado.

- **Cadeado fechado** — só a administração muda aquele campo.
- **Cadeado aberto** — a sede pode mudar.

Clique nos cadeados que quiser inverter e use **"Salvar cadeados"**. A mudança
vale para todas as imagens **Oficiais** daquele modelo; as imagens **Livres**
continuam editando tudo, independentemente dos cadeados (veja o perfil logo
abaixo).

É assim que se faz, por exemplo, "nesta temporada as sedes escolhem a RAM
mínima, mas o firewall continua fechado": abra o cadeado da RAM mínima e deixe
o do firewall fechado.

Quem preferir a API:

```bash
# ver os campos e o estado de cada cadeado
curl https://nutellaboot.naquadah.com.br/api/v1/models/maratonalinux2604/schema \
    -H "Authorization: Bearer $NB3_ADMIN_KEY"

# abrir a RAM mínima e fechar o fuso horário
curl -X PUT https://nutellaboot.naquadah.com.br/api/v1/models/maratonalinux2604/schema/locks \
    -H "Authorization: Bearer $NB3_ADMIN_KEY" \
    -H 'Content-Type: application/json' \
    -d '{"locks": {"MINRAM": false, "TIMEZONE": true}}'
```

Só a chave `locked` de cada campo é alterada: rótulos, tipos e opções do
formulário ficam intactos. Campos que não existem no modelo são recusados com
erro, para um nome errado não passar despercebido.

### Perfil da imagem: Oficial ou Livre

Quais campos ficam bloqueados depende do **perfil** da imagem:

| Perfil | Quem edita os campos obrigatórios | Uso típico |
|---|---|---|
| **Oficial** | só a administração | sedes de prova: RAM mínima, firewall, uso de pendrive e página inicial são iguais em todas |
| **Livre** | o próprio dono da imagem | laboratórios e cursos: a pessoa manda na imagem inteira |

Como se define:

- **Criando pelo `/admin/`**: o formulário tem um seletor de perfil (padrão
  Oficial). A criação em massa (TSV) sempre gera imagens Oficiais.
- **Convites**: ao gerar um código você escolhe o perfil que as imagens dele
  vão ter — o padrão é **Livre** (quem cria a própria imagem manda nela). Marque
  Oficial se estiver convidando uma sub-sede que precisa seguir as regras.
- **Trocando depois**: na lista de imagens do `/admin/` cada linha mostra uma
  pílula **Oficial/Livre** e um botão que alterna — é assim que você "volta uma
  imagem com tudo liberado", sem recriar nada nem invalidar links.

Quais campos são obrigatórios em cada perfil é decisão do **modelo** (campos
marcados `locked` no `schema.json`), não da imagem. Ou seja: dá para ter um
modelo de prova rígido e um modelo de laboratório mais frouxo.

### Wallpaper: agora é upload

Não existe mais campo de URL. A pessoa escolhe o arquivo (PNG ou JPEG) e clica
em enviar; o servidor guarda, calcula o md5 e passa a servir para as máquinas.

No NutellaBoot 2 era uma URL colada à mão. O servidor baixava a imagem **na
hora de salvar**, e uma URL ruim derrubava o salvamento inteiro da
configuração. Pior: na máquina, o download do wallpaper acontecia no boot e,
quando falhava, parava num `Continue anyway? (Y/n)` esperando alguém digitar.
Hoje, falha de wallpaper só registra um aviso e o boot segue.

Se os botões de enviar e remover aparecerem desabilitados, o papel de parede
daquela imagem foi **travado pela organização** na criação (veja "Uma de cada
vez", na seção 2). Nesse caso só a administração troca — o que costuma ser
proposital em eventos, para todas as salas ficarem iguais.

### Senha de emergência da tela de bloqueio

Definida no configureitor, guardada apenas como hash (`salt$sha256`) e enviada
à máquina dentro do `/etc/.nb3`. Digitada na própria tela de bloqueio, ela
destrava sem depender da rede — útil quando o wifi cai no meio da prova.

A senha é digitada às cegas: a tela não mostra campo de texto. Digite e tecle
Enter.

## 4. Durante a prova

### O painel do laboratório

```
https://nutellaboot.naquadah.com.br/hotconfig/?id=26spsp&tk=nb3i_...
```

Cada máquina é um cartão, atualizado sozinho (o servidor empurra as mudanças —
não há botão de recarregar):

- **borda verde**: online e saudável
- **borda amarela**: sem contato há pouco tempo
- **borda vermelha**: em alerta (memória, carga ou swap acima do limite)
- **borda cinza**: offline
- **cadeado**: tela bloqueada
- **contorno vermelho + 🔌**: dispositivo USB conectado nesta máquina

O cartão mostra o time vinculado, o lugar, uso de memória, carga e estado do
firewall. Clique duplo abre o detalhe, com duas abas: **Estado agora** (a
telemetria completa) e **Logs** (o journal que a máquina envia).

Filtros rápidos: todas, com dispositivo, bloqueadas, em alerta, sem time,
offline.

### Pendrive e celular: a faixa vermelha

Quando alguém conecta um **pendrive**, um **celular** (transferência de
arquivos) ou liga **tethering** numa máquina, uma faixa vermelha aparece no
topo do painel, pisca e apita — uma linha por dispositivo, com a máquina, o
time, o modelo e a hora.

**A faixa não some sozinha.** O dispositivo pode ser removido no segundo
seguinte; o alerta fica até um fiscal clicar em *Dispensar*, e o clique é
registrado com nome e hora. Quem espeta um pendrive por cinco segundos não
escapa do registro. O alerta também sobrevive a reboot da máquina, a recarga da
página e a reinício do servidor.

O som só toca depois de você clicar em **🔔 Ativar som** (é uma regra do
navegador, não uma escolha do sistema); a escolha fica guardada naquele
computador.

O que é detectado, e como:

| Situação | Como é vista |
|---|---|
| Pendrive, HD externo, leitor de cartão | dispositivo de bloco no barramento USB |
| Celular em modo de transferência (MTP/PTP) | propriedade `ID_MTP_DEVICE` ou interface de câmera |
| Tethering pelo celular (RNDIS/CDC/NCM) | interface de rede que aparece no barramento USB |

O **pendrive de boot não dispara o alarme** (é reconhecido pela label
`NB3CFG`), porque em muitas salas ele fica espetado o dia todo. Dispositivo já
conectado quando a máquina liga também é reportado.

A detecção é feita por regra de `udev`, não por varredura: o ciclo de
telemetria é de ~45 segundos e um pendrive espetado por dez segundos passaria
batido.

Para ver tudo o que já apareceu numa máquina, incluindo o que foi dispensado:

```bash
curl "$SERVER/api/v1/site-images/26spsp/machines/$MAC/alerts/history" \
    -H "Authorization: Bearer $TOKEN"
```

### Logs da máquina

Cada máquina envia o journal do boot na partida e, a cada 5 minutos, só o que
apareceu desde o envio anterior. É o que responde "o que aconteceu naquela
máquina às 14h32" **depois** que a prova acabou.

No painel: clique duplo no cartão → aba **Logs**. Ou pela API:

```bash
curl "$SERVER/api/v1/site-images/26spsp/machines/$MAC/logs?tail=2000" \
    -H "Authorization: Bearer $TOKEN"
```

A resposta traz também as confirmações dos comandos enviados àquela máquina
(quando chegou e com que resultado).

Não enche disco: o teto é de 1 MiB por envio e 2 MiB por máquina, mantendo
sempre a parte mais recente. Cem máquinas cabem em 200 MB.

### Ações em massa

Clique nos cartões para selecionar (ou use "Selecionar todas", que respeita o
filtro ativo) e escolha a ação: bloquear/desbloquear tela, limpar a home,
ligar/desligar firewall, zerar contagem de editores, reiniciar, desligar.

O bloqueio de tela chega em **poucos segundos**. As máquinas ficam penduradas
numa requisição de longa duração, e o servidor responde no instante em que você
manda o comando. No NutellaBoot 2, com polling de 5 a 30 segundos somado ao
atraso configurado, passava de 30 segundos.

O bloqueio usa dois caminhos ao mesmo tempo: grava o estado (que a própria tela
consulta a cada 4 segundos) **e** enfileira o comando (que o agente executa).
Se um falhar, o outro resolve. E matar o processo da tela não destrava: o
agente relança em até 3 segundos enquanto o estado for "bloqueada".

### Vínculo time ↔ máquina

O roster (lista de times, com nome, organização, país e lugar) vem do MOJ ou é
enviado pela API, junto com os logotipos das instituições. O vínculo aponta
para uma entrada do roster:

```bash
curl -X PUT "$SERVER/api/v1/site-images/26spsp/machines/$MAC/binding" \
    -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' \
    -d '{"user_id": "team-001"}'
```

A tela de bloqueio da máquina passa a mostrar o logotipo da instituição, o nome
do time, a bandeira do país e o lugar. Esses dados são cacheados em disco no
momento do bloqueio: se a rede cair, a tela continua correta.

### Quando uma máquina some do painel

Ela deixa de reportar. Confira, nessa ordem: a máquina está ligada? tem rede?
Se rebootou, ela reaparece com o mesmo MAC e o vínculo continua. Se trocou de
placa de rede, aparece como máquina nova e o vínculo precisa ser refeito.

## 5. Runbook do dia da prova

### Véspera

- [ ] Camada base gerada e registrada no modelo (`nb3-gerar-squash`)
- [ ] `vmlinuz` e `initrd.img` atualizados (`nb3-build-initrd`)
- [ ] Pendrives gravados e testados em **pelo menos uma máquina real** da sede
- [ ] `wifi.conf` com as redes da sede (e a rede reserva)
- [ ] `nutellaboot.conf` com a sede certa e a chave de boot certa
- [ ] Configuração revisada no configureitor (fuso, teclado, página do juiz)
- [ ] Wallpaper enviado
- [ ] Senha de emergência da tela de bloqueio definida e anotada
- [ ] Roster carregado, logotipos enviados
- [ ] Uma máquina designada como semeadora (`Semear a imagem`), ligada cedo

### Manhã

- [ ] Ligar primeiro a máquina semeadora e esperar ela terminar o boot
- [ ] Bootar as demais (a primeira leva minutos; as outras puxam da semeadora)
- [ ] **Recolher os pendrives assim que a mensagem aparecer** (veja abaixo)
- [ ] Conferir no painel: todas as máquinas online?
- [ ] Vincular os times aos lugares
- [ ] Testar bloquear e desbloquear **uma** máquina antes de fazer na sala toda

#### Quando tirar o pendrive

A instrução mudou em relação às versões anteriores. **Não é mais "quando o
kernel começar a mostrar mensagens"**: agora a própria máquina avisa, e o
momento é bem mais cedo — antes de qualquer coisa de rede.

```
  ┌────────────────────────────────────────────────────────────┐
  │  PODE RETIRAR O PENDRIVE AGORA                              │
  │  YOU CAN REMOVE THE USB DRIVE NOW                           │
  │  YA PUEDE RETIRAR LA MEMORIA USB                            │
  └────────────────────────────────────────────────────────────┘
```

Assim que esse quadro aparece, o pendrive não é mais lido: o GRUB já colocou
kernel e initrd na memória, e o initrd acabou de copiar o `nutellaboot.conf`
e o `wifi.conf` para a RAM e desmontar a partição. Todo o resto do boot —
rede, download das camadas, montagem do sistema — acontece sem ele.

Na prática, isso permite ligar as máquinas em sequência com poucos pendrives:
liga, espera o aviso (poucos segundos), tira e leva para a próxima, enquanto a
primeira continua baixando sozinha.

### Antes do início

- [ ] Bloquear a tela de todas as máquinas
- [ ] Conferir que todos os cartões mostram o cadeado
- [ ] Conferir que a tela mostra o time certo em cada lugar
- [ ] Firewall ligado em todas

### Durante

- [ ] Desbloquear tudo no sinal de largada
- [ ] Olhar o painel de tempos em tempos: cartões vermelhos indicam máquina com
      problema de recursos antes que a equipe reclame
- [ ] Máquina travada: reiniciar por ali mesmo; a home persistente preserva o
      trabalho

### Fim

- [ ] Bloquear as telas ao encerrar
- [ ] Desligar as máquinas pelo painel
- [ ] Guardar o CSV de credenciais em lugar seguro (ou apagar, se não for
      reaproveitar)

## 6. Solução de problemas

### A máquina não boota / o GRUB não aparece

Confirme que a máquina está em UEFI e que o pendrive foi gravado com `dd`
(copiar o arquivo pelo gerenciador de arquivos não funciona). Teste a imagem
sem hardware:

```bash
tools/nb3-qemu-shot maratona2026.img /tmp/tela.png --wait 8
```

Se o menu do GRUB aparecer no screenshot, o pendrive está bom e o problema é da
máquina (Secure Boot, ordem de boot, porta USB).

### "IMAGEROOT não definido"

O `nutellaboot.conf` da partição está sem a linha `IMAGEROOT=` (ou o pendrive
foi gravado no modo genérico e ninguém preencheu). Monte o pendrive em qualquer
computador e edite.

### "chave de boot inválida ou ausente"

O `NB_BOOT_KEY` do `nutellaboot.conf` não bate com o da imagem. Pegue a atual:

```bash
curl "$SERVER/api/v1/site-images/26spsp/boot-key" -H "Authorization: Bearer $NB3_ADMIN_KEY"
```

Se alguém rodou `boot-key/rotate`, **todos** os pendrives daquela imagem
precisam ser atualizados. Por isso a rotação só existe por linha de comando: o
console mostra a chave, mas não oferece um botão para trocá-la — é a única
operação do sistema que invalida material já distribuído fisicamente.

### A tela vermelha "NO DISK"

A máquina não achou onde guardar o sistema: precisa de uma partição
ext3/ext4/NTFS gravável com pelo menos 15 GB **livres**, para o cache das
camadas e a home persistente. Nada é apagado — só espaço livre é usado.

**A própria tela diz a causa provável e o que fazer.** Ela lista cada partição
encontrada e por que foi recusada, e escolhe entre quatro diagnósticos:

| O que a tela diz | O que fazer |
|---|---|
| `WINDOWS FAST STARTUP` | o Windows foi hibernado, não desligado, e deixou o disco travado. Iniciar o Windows e rodar `shutdown /s /t 0`, ou desligar o Fast Startup nas Opções de Energia |
| `NOT ENOUGH FREE SPACE` | há disco, mas nenhum com 15 GB livres |
| `THE DISK WAS NOT DETECTED AT ALL` | controladora em RAID / Intel RST; trocar para AHCI no setup da BIOS |
| `NO SUPPORTED FILESYSTEM` | só exFAT/FAT32, ou partição com BitLocker (que não pode ser lida) |

A máquina reinicia sozinha 60 segundos depois — tempo para ler ou fotografar a
tela.

As demais telas vermelhas seguem o mesmo padrão: `NO NETWORK` (cabo, switch,
wifi), `NO SERVER` (nome do servidor, portal cativo, relógio da BIOS errado),
`NO IMAGE` (falta `IMAGEROOT=` no pendrive), `LOW RAM`, `NO VM` e `REMOVED`.

> As mensagens do boot são **em inglês**, em todas as sedes. É a única parte do
> sistema que não é traduzida: quando a mensagem aparece, muitas vezes não há
> rede nem disco para carregar um dicionário. A tela de bloqueio e o agente
> continuam seguindo o campo *Idioma* do formulário.

### O wifi não conecta

Verifique o `wifi.conf`: os campos são separados por **TAB**, não por espaço.
Rede oculta precisa da palavra `hidden` no terceiro campo. A máquina tenta a
rede cabeada primeiro; a mensagem "wifi não associou em 30s" significa que o
`wpa_supplicant` subiu mas não completou o handshake — senha errada, sinal
fraco ou rede fora do ar.

### Seeder aparece e some da lista

É o comportamento correto. O seeder renova o registro a cada 60 segundos, e o
servidor descarta quem para de renovar (TTL de 180 s por padrão, em
`data/server.json`). Uma máquina desligada some sozinha da lista em até 3
minutos — no NutellaBoot 2 ela ficava para sempre, e 1 em cada N boots caía
naquele seeder morto.

Confira quem está semeando:

```bash
curl "$SERVER/api/v1/site-images/26spsp/seeders" -H "Authorization: Bearer $TOKEN"
```

### O wallpaper não apareceu

O wallpaper só é aplicado se o md5 estiver na configuração da imagem no momento
do boot — quem enviou depois das máquinas ligarem precisa reiniciá-las. Se o
download falhar, o boot **segue** e registra aviso; a máquina fica com o
wallpaper padrão.

### A tela de bloqueio não abriu

Confira se o comando chegou (o cartão da máquina mostra o cadeado). Se o estado
está bloqueado no servidor mas a tela não apareceu, o problema é local: o
agente relança a cada 3 segundos, então verifique se o `agent.sh` está rodando
(`journalctl -t nb3-agent` na máquina).

Em Wayland não existe captura global de teclado para aplicações comuns: a tela
cobre todos os monitores, fica sempre no topo e é relançada se for morta, mas
não é um bloqueio de sessão do GNOME. É a mesma limitação prática do
NutellaBoot 2, agora com o relançamento automático.

### O comando não chegou na máquina

O agente fica pendurado numa requisição de até 25 segundos; se a rede oscilar,
ele reconecta e recebe o que ficou pendente — comandos não se perdem, ficam na
fila até serem confirmados. Verifique se a máquina aparece como online no
painel. Se estiver offline, o comando será entregue quando ela voltar.

---

## Capacidade: o que a máquina aguenta

Medido, não estimado — `tools/nb3-carga` simula o ciclo de vida real de N
máquinas (boot, telemetria a cada 45 s e long-poll contínuo) e mede o que a
sala sente.

**1600 máquinas, um worker uvicorn**, em servidor de 16 núcleos:

| | mediana | p95 | pior |
|---|---|---|---|
| `stuff` (o boot inteiro, 1600 de uma vez) | 30 ms | 60 ms | 99 ms |
| `manifest` | 16 ms | 58 ms | 93 ms |
| telemetria (`status`) | 4 ms | 976 ms | 5,1 s |
| **comando visto pela máquina** | **750 ms** | 1,3 s | 1,4 s |

Zero erros. O worker ficou entre **24% e 60% de um núcleo**, com 108 MB de RSS
e ~1600 conexões presas.

Duas armadilhas que essa medição ensinou, e que valem para quem for repeti-la:

- **um processo Python não dirige 1600 conexões.** A primeira medida acusava
  p95 de 69 s no `stuff`; era o gerador engasgando, não o servidor — que estava
  em 24% de um núcleo. Use `--offset` e vários processos (foram oito);
- **só quem enfileira o comando sabe o instante zero.** Um processo auxiliar
  medindo "tempo desde que meu long-poll começou" dá mediana de metade da
  janela de espera, que se parece exatamente com "o sinal não acorda ninguém".
  O número real era 750 ms.

O que dimensiona o servidor não é o tráfego: são as **conexões ociosas**. Cada
máquina segura uma esperando comando, o tempo todo. Daí `LimitNOFILE=65535` na
unidade e `worker_connections 8192` no nginx — o padrão de 1024 descritores
derruba a sala inteira, e o sintoma é "não conecta mais ninguém".

### O mesmo teste contra a produção, por HTTPS

| | mediana | p95 | pior |
|---|---|---|---|
| `stuff` | 189 ms | 6,4 s | 6,9 s |
| telemetria | 79 ms | 9,5 s | 32 s |

O worker ficou em **86% de um núcleo**, com carga 0,61 numa máquina de 16.

E houve ~3000 `ConnectTimeout` — que **não foram do servidor**. Ele contou
`ListenOverflows 0`, `ListenDrops 0`, `TCPReqQFullDrop 0`, e o nginx registrou
14 430 respostas 200 sem um único erro. As falhas apareceram do lado do
gerador (`TcpAttemptFails 3183`, `SynRetrans 50 658` na máquina que gerava):
1600 conexões TLS saindo de **um IP só**, por um NAT só.

A prova real não é assim — são ~50 sedes de ~35 máquinas, cada uma na sua
rede. O que este teste prova é que o servidor absorve tudo que chega até ele;
o que ele **não** prova é o caminho, porque o caminho do teste era um funil que
a prova não tem.

> **A margem que sobra é de um núcleo.** 1600 máquinas custam 86% de UM worker,
> e worker só pode haver um (invariante 2). Para 2000 a conta fica apertada. Se
> chegar perto do limite, o caminho não é subir workers — é tirar os sinais de
> long-poll e SSE da memória do processo, e isso é mudança de arquitetura.

Como repetir:

```bash
# oito geradores contra a mesma sede, 200 máquinas cada
for i in $(seq 0 7); do
  [ "$i" = 0 ] || AUX=--comando-so-leitor
  .venv/bin/python tools/nb3-carga --server "$SERVER" --key "$NB3_ADMIN_KEY" \
      --modelo maratona2026 --maquinas 200 --offset $((i*200)) \
      --segundos 150 --rampa 60 $AUX &
done; wait
```

---

## Instalar o servidor (do zero)

O que está no ar hoje, feito exatamente assim em
`nutellaboot.mdp.naquadah.com.br` (Ubuntu 24.04).

```bash
apt-get install -y python3-venv python3-pip nginx certbot python3-certbot-nginx \
    squashfs-tools rsync mtools grub-efi-amd64-bin grub-pc-bin grub-common

adduser --system --group --home /var/lib/nutellaboot3 --shell /usr/sbin/nologin nutellaboot
install -d -o nutellaboot -g nutellaboot -m 0750 /var/lib/nutellaboot3

git clone https://github.com/bcribas/nutellaboot.git /opt/nutellaboot3
python3 -m venv /opt/nutellaboot3/.venv
/opt/nutellaboot3/.venv/bin/pip install fastapi "uvicorn[standard]" python-multipart httpx

install -m 0644 /opt/nutellaboot3/systemd/nutellaboot3.service /etc/systemd/system/
install -m 0644 /opt/nutellaboot3/deploy/sysctl-nutellaboot3.conf /etc/sysctl.d/60-nutellaboot3.conf
sysctl --system

cd /opt/nutellaboot3
NB3_DATA_ROOT=/var/lib/nutellaboot3 .venv/bin/python tools/nb3-init --id producao   # IMPRIME a chave
chown -R nutellaboot:nutellaboot /var/lib/nutellaboot3

systemctl enable --now nutellaboot3
```

**A chave de administração sai uma vez só.** Em disco fica apenas o hash. Guarde
antes de fechar o terminal.

### nginx e certificado

```bash
install -d /etc/nginx/snippets
install -m 0644 /opt/nutellaboot3/deploy/nutellaboot3-proxy.conf /etc/nginx/snippets/
rm -f /etc/nginx/sites-enabled/default
# e os globais em nginx.conf: worker_processes auto, worker_rlimit_nofile 65535,
# worker_connections 8192, multi_accept on

# O certificado PRIMEIRO: o arquivo de configuração aponta para ele, e o nginx
# não inicia apontando para arquivo que não existe.
certbot certonly --webroot -w /opt/nutellaboot3/web -d nutellaboot.mdp.naquadah.com.br

install -m 0644 /opt/nutellaboot3/deploy/nginx-nutellaboot3.conf /etc/nginx/sites-available/nutellaboot3
ln -sf /etc/nginx/sites-available/nutellaboot3 /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

> O TLS está no arquivo versionado, e não escrito pelo `certbot --nginx`, por um
> motivo aprendido apanhando: com o certbot dono do bloco 443, reinstalar o
> arquivo no deploy APAGAVA o HTTPS — e sem HTTPS nenhuma máquina boota. Assim
> reinstalar é idempotente. A renovação continua automática (`certbot renew`),
> e o desafio sai pela porta 80.

**Sem certificado válido nada boota**: o initrd verifica TLS em todo download, e
essa é uma invariante do projeto. Confira do lado de fora antes de seguir:

```bash
curl https://nutellaboot.mdp.naquadah.com.br/api/v1/health
curl https://nutellaboot.mdp.naquadah.com.br/boot/v3/sanity      # penguin
```

### Publicar no servidor de arquivos

O servidor envia camadas e imagens de pendrive para o `files.mdp` por rsync
sobre SSH, com um usuário **sem privilégio** e uma chave que só sabe fazer isso.

No `files.mdp`:

```bash
adduser --system --group --home /var/lib/nb3pub --shell /bin/sh nb3pub
chgrp nb3pub /var/www/html/maratonalinux /var/www/html/mlbootimages
chmod 2775   /var/www/html/maratonalinux /var/www/html/mlbootimages   # setgid
```

No servidor do NutellaBoot, como o usuário do serviço:

```bash
sudo -u nutellaboot ssh-keygen -t ed25519 -N "" -f /var/lib/nutellaboot3/.ssh/id_ed25519
ssh-keyscan -t ed25519 files.mdp.naquadah.com.br > /var/lib/nutellaboot3/.ssh/known_hosts
```

E a pública entra no `authorized_keys` do `nb3pub` **restrita**:

```
restrict,command="/usr/bin/rrsync -wo /var/www/html" ssh-ed25519 AAAA... nutellaboot3@...
```

`restrict` tira porta, agente, X11, tty e encaminhamento; o `command` prende a
chave ao rsync em modo **somente escrita** sob `/var/www/html`. Mesmo vazando,
ela não lê nada nem abre shell — dá para conferir:

```bash
sudo -u nutellaboot ssh nb3pub@files.mdp.naquadah.com.br "cat /etc/shadow"
# /usr/bin/rrsync error: SSH_ORIGINAL_COMMAND does not run rsync
```

O `known_hosts` pré-carregado não é zelo: o serviço roda com `BatchMode=yes` e
sem ele o primeiro envio falharia pedindo confirmação que ninguém vai dar.

Por fim, no `data/server.json`:

```json
"publish": {
  "enabled": true,
  "host": "files.mdp.naquadah.com.br",
  "user": "nb3pub",
  "paths": {"layers": "maratonalinux", "usb": "mlbootimages"}
}
```

Os caminhos são **relativos** à raiz do `rrsync`; absoluto seria recusado.

### Atualizar

**A produção não recebe edição manual.** Conserto se faz no repositório, e
chega aqui por `git pull`. Editar um arquivo direto no servidor deixa a máquina
diferente do repositório sem nada registrando a diferença — e o próximo
reinstall apaga a correção em silêncio.

```bash
cd /opt/nutellaboot3
git pull

# só se o que mudou estiver em deploy/ ou systemd/
install -m 0644 deploy/nginx-nutellaboot3.conf /etc/nginx/sites-available/nutellaboot3
install -m 0644 deploy/nutellaboot3-proxy.conf /etc/nginx/snippets/
install -m 0644 deploy/sysctl-nutellaboot3.conf /etc/sysctl.d/60-nutellaboot3.conf
install -m 0644 systemd/nutellaboot3.service /etc/systemd/system/
nginx -t && systemctl reload nginx
systemctl daemon-reload

systemctl restart nutellaboot3
curl -s https://nutellaboot.mdp.naquadah.com.br/api/v1/health
```

O `stuff` é lido do disco a cada boot, então mudança em `client/stuff/` chega às
máquinas sem reiniciar o serviço. Rota nova, sim, precisa de reinício.
