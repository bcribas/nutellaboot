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
sudo -E NB3_ADMIN_KEY=nb3a_... NB3_BASE_URL=https://nutellaboot.mdp.naquadah.com.br \
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
export NB3_BASE_URL=https://nutellaboot.mdp.naquadah.com.br
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
export NB3_BASE_URL=https://nutellaboot.mdp.naquadah.com.br
export NB3_ADMIN_KEY=nb3a_...

tools/nb3-camada-telemetria --dry-run                       # ver antes
tools/nb3-camada-telemetria --model maratona2026 --publish
```

Na produção, rode como o usuário `nutellaboot` com
`NB3_DATA_ROOT=/var/lib/nutellaboot3`: o blob vai para `blobs/` do diretório
de dados e o envio ao servidor de arquivos usa a chave ssh dele. É um
`--model` por modelo em uso com camada `telemetry` (`GET /api/v1/models`
lista; `replace_role` tira a anterior de cada um).

**Mudou algo em `client/telemetry/`? Suba a versão** em
`client/telemetry/usr/share/mlog/VERSION` (ano.mês.sequência) no mesmo commit. É
o `agent_version` que cada máquina reporta, e o que responde "essa sede já está
com o agente novo?" sem abrir máquina: `GET …/machines` traz
`status.agent_version` e `status.capabilities`. A máquina só troca de agente no
boot seguinte à publicação.

Na produção o nome público não conecta de dentro do servidor (falta hairpin no
NAT): use `NB3_BASE_URL=http://127.0.0.1:8890`. E a chave de admin está em
`/root/nutellaboot3-admin.key` junto com outro texto na mesma linha: extraia
com `grep -o "nb3a_[0-9a-f]*" /root/nutellaboot3-admin.key | head -1` (passar o
arquivo cru dá `401`).

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

O build confere o resultado e **recusa** initrd incompleto: ferramentas do
caminho de download, `wpa_supplicant`, os módulos de crypto do WPA
(`ccm`/`cmac`/`michael_mic`) e os canários de firmware do iwlwifi
(`so-a0-hr-b0`, `ty-a0-gf-a0`, `QuZ-a0-hr-b0` — as famílias Intel que já
ficaram de fora em silêncio e deixaram um AX201 de campo sem wifi). O
initrd sai com ~186 MiB.

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
    --server https://nutellaboot.mdp.naquadah.com.br \
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

#### Sala que boota pela rede (PXE/iPXE)

Sede com DHCP + iPXE não precisa de pendrive. Ela serve três arquivos do
próprio servidor PXE — `vmlinuz`, `initrd.img` e o `nutellaboot.conf` da sala
(o mesmo do pendrive) — e o conf entra como **segundo initrd, com nome**:

```
#!ipxe
dhcp
kernel vmlinuz boot=nutellaboot noresume pcie_aspm=off net.ifnames=0 persistenthome=y
initrd initrd.img
initrd nutellaboot.conf /nutellaboot.conf
boot
```

O kernel e o initrd saem com a chave de boot da sala (a linha `NB_BOOT_KEY` do
conf):

```bash
for f in vmlinuz initrd.img; do
    curl -fO -H "X-NB-Boot-Key: nb3b_..." "$SERVER/boot/v3/26spsp/usbfile/$f"
done
```

As opções do menu do pendrive são parâmetros da mesma linha `kernel`:
`cleanhome=y`, `persistenthome=n` (modo live), `factoryreset=y`. O porquê e o
que muda no boot estão em `docs/boot-flow.md`, seção *Boot pela rede*; a página
para as sedes é a de instalação na wiki.

**Reconstruir o initrd deixa essas sedes para trás**: os pendrives se
atualizam sozinhos, o servidor PXE da sede não. As máquinas continuam bootando
e avisam no console (`the network boot files are out of date`). Avise as sedes
de netboot para baixarem os dois arquivos de novo — e, se o **kernel** da camada
base mudou, antes da prova: com o `vmlinuz` velho o sistema montado fica sem os
módulos do kernel.

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
curl -X PATCH https://nutellaboot.mdp.naquadah.com.br/api/v1/site-images/26spsp \
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
inicial). A partir daí o navegador guarda uma **sessão de 30 dias a partir do
último uso** (usar o console renova o prazo): recarregar a página, abrir
outra aba ou voltar no dia seguinte não pedem a chave de novo. A página
inicial diz se você já está dentro e até quando. A chave em si não fica
guardada pela página — o que fica é um cookie que nenhum script consegue
ler. Mas o campo é um formulário de senha normal: **se o navegador oferecer
salvar a chave, aceite** — o gerenciador de senhas do navegador é o lugar
certo para ela, e o autopreenchimento vale na página inicial e no `/admin/`.
O botão do olho no campo mostra o que foi colado, para conferir antes de
entrar; espaços e quebras de linha colados junto são descartados.

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

O endereço raiz do servidor (`https://nutellaboot.mdp.naquadah.com.br/`) é a porta
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
https://nutellaboot.mdp.naquadah.com.br/configureitor/?id=26spsp&tk=nb3i_...
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
curl https://nutellaboot.mdp.naquadah.com.br/api/v1/models/maratonalinux2604/schema \
    -H "Authorization: Bearer $NB3_ADMIN_KEY"

# abrir a RAM mínima e fechar o fuso horário
curl -X PUT https://nutellaboot.mdp.naquadah.com.br/api/v1/models/maratonalinux2604/schema/locks \
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
destrava sem depender da rede — útil quando o wifi cai no meio da prova. Quem
confere é o agente (root), nunca a tela: a senha desce por um FIFO e o hash
não sai do arquivo de segredos.

A senha é digitada às cegas: a tela não mostra campo de texto. Digite e tecle
Enter — o teclado numérico também vale. O destravamento local FICA: o estado
`locked` do servidor não retrava a máquina sozinho. Para retravar, mande o
comando de travar de novo (hotconfig) — comando novo vale mais que o
destravamento local.

### A licença do CLion

A chave de licença é DADO, não código: o repositório é público e ela nunca
entra no git. Instale-a no servidor:

```bash
install -m 600 clion.key /opt/nutellaboot3/data/secret/clion.key
```

Com o arquivo presente, o stuff de toda sede passa a anunciar
`NB_CLION_KEY`/`NB_CLION_VERSION`, e cada máquina baixa a chave no boot pela
rota autenticada (`/boot/v3/<sede>/clionkey`, com a chave de boot — o
`/secret/` público do NutellaBoot 2 acabou). A versão padrão é `CLion2026.1`;
para trocar quando o CLion mudar, sem redeploy:

```bash
# em data/server.json
{"clion": {"version": "CLion2027.1"}}
```

Sem o arquivo, nada quebra: o stuff não anuncia e as máquinas seguem sem
licença — como qualquer instalação fora da maratona.

### Compartilhar o dashboard

O `/dashboard/` é a tela de transmissão: placar da frota, mapa de calor por
região, histórico com recorte de período e as visões de hardware, editores e
disco. Para pôr num telão ou entregar a um jornalista SEM entregar o console:

1. no `/admin/`, cartão da frota, **Compartilhar dashboard** — sai uma URL
   pronta (`/dashboard/?tk=nb3s_…`). A chave aparece UMA vez;
2. a chave só LÊ os agregados: não abre hotconfig, não roda comando, não vê o
   detalhe por máquina no zoom;
3. para trocar, **Revogar** e criar outra — a URL antiga morre na hora.

O seletor de período ("30 min · 2 h · 5 h · 24 h · desde…") fica na URL:
`/dashboard/?since=<epoch>` abre já recortado — o link do telão pode apontar
para o início da prova.

Ao compartilhar, escolha o que o link mostra: **o link segue a minha seleção**
(o padrão: ele mostra a visão da frota da administração, e muda na hora em que
você a muda) ou **estas imagens** (um recorte fixo por globs, como `26br*`). O
link que segue a seleção nunca se alarga sozinho, e os globs continuam sendo o
teto.

### A visão da frota: o que o dashboard e os laboratórios mostram

A administração enxerga tudo, então o painel dela era a soma das sedes da prova
com os laboratórios de todo mundo que entrou por convite. Agora há um recorte,
**gravado no servidor** (vale em qualquer navegador, no telão e no link
compartilhado que o segue):

| Visão | O que mostra |
|---|---|
| **só as minhas** (o padrão) | as imagens da administração; para um sub-admin, as dele |
| **todas** | tudo o que você pode ver |
| **por dono** | as imagens dos donos marcados (só a administração) |
| **escolhidas à mão** | as sedes marcadas na tela dos laboratórios |

O seletor está no cartão da frota do `/admin/` e no topo do `/laboratorios/`.
Para escolher à mão: em `/laboratorios/` marque **mostrar todas, sem salvar** (as
sedes de fora da visão aparecem esmaecidas), marque as que você quer, escolha
**escolhidas à mão** e **Gravar**. Imagem criada depois disso fica **fora** até
ser escolhida, e a tela avisa ("N imagens novas fora da seleção"): o laboratório
novo de alguém não pula para o telão sozinho. `dashboard_hidden` continua sendo
exclusão dura, acima de qualquer visão.

Toda lista de imagens (no `/admin/` e nos laboratórios) diz **de quem é** cada
uma: a administração, ou o rótulo do convite de quem a criou. Mude o rótulo em
**Convites → Editar**; ele acompanha em todas as telas. O código do convite
nunca aparece nessas listas: ele é a credencial de console daquela pessoa.

### Chaves: ver, criar, revogar

O cartão **Chaves** do `/admin/` (só da administração) reúne o que antes pedia
`curl` ou acesso ao servidor:

- **Chaves de administração**: a lista (quem criou, quando, último uso, quantas
  sessões abertas, e qual é a desta sessão), criar e revogar. Criar e revogar
  pedem **a sua chave de novo**: o navegador lembra a sessão, não a pessoa.
  Não existe "rotacionar": crie a nova, **entre com ela**, e só então revogue a
  velha. A última chave não se revoga. Foi assim que a chave de admin que passou
  pela conversa com o assistente do MOJ pôde ser trocada sem acesso ao servidor.
- **Chaves de serviço** (o MOJ, o telão): todas aparecem, com escopos, globs,
  criada em e último uso. Criar com os escopos do catálogo; **Rotacionar** dá
  uma chave nova com o mesmo nome (a antiga morre na hora); nome repetido é
  erro, não sobrescrita. O recomendado é uma chave por evento.
- **Auditoria**: o que foi feito com chaves e convites, por quem e de onde. Não
  guarda segredo nenhum.

Em **Sub-administradores**: suspender (corta o console sem apagar nada), ajustar
cotas, ver o uso e o último acesso. Em **Convites**: **Revogar** agora é
reversível (fecha o console e a criação de imagens, e não deixa nada órfão);
**Apagar** é o definitivo, e avisa o que ficaria sem dono antes de ir.

Na linha de cada imagem, **Chaves** mostra a chave de boot (a que vai no
`nutellaboot.conf`) e a rotaciona, e troca a **chave de máquina**, que não tinha
rotação. A máquina só recebe a chave de máquina no boot: use a **carência**
(12 h por padrão) para as máquinas ligadas não ficarem mudas; "sem carência" é
para chave vazada, e é recusada enquanto houver máquina travada (ela não
receberia o destravar).

`last_used` é aproximado (vai ao disco uma vez por minuto): serve para achar a
chave esquecida, não para perícia.

## 4. Durante a prova

### O painel do laboratório

```
https://nutellaboot.mdp.naquadah.com.br/hotconfig/?id=26spsp&tk=nb3i_...
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
firewall. Clique duplo abre o detalhe, com seis abas: **Gráficos** (memória,
carga e editores no período), **Estado** (a telemetria completa), **Logs** (o
journal que a máquina envia), **Time** (vincular, mover, desvincular, e o
histórico: "trocou de time" aparece marcado), **Alertas** (o histórico da
máquina, com "dispensar todos") e **Ordens** (cada comando que ela confirmou,
com a saída, e os que caducaram).

Filtros rápidos: todas, com dispositivo, bloqueadas, em alerta, sem time,
offline. O seletor "vistas nas últimas N h" tira da grade quem não reporta há
mais tempo (fica lembrado no navegador).

Depois de mandar uma ordem, a barra acima da grade acompanha quem confirmou,
quem ainda espera e quem caducou (10 minutos), com o detalhe por máquina. Ela
vive dos eventos do painel e da rota `GET …/commands/{id}`.

A tela tem quatro visões, no alto: **Máquinas** (a grade), **Times** (o
roster e os vínculos), **Sala** (as máquinas comparadas entre si no período:
ranking pelo pico de memória, swap, carga, pressão ou disco, ou miniaturas na
mesma escala; clique abre o detalhe) e **Alertas** (o histórico da sede
inteira, com quem dispensou o quê, e o CSV). A faixa vermelha fica visível em
todas.

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

O alerta é de **mudança de estado**: alguém espetou algo com a máquina já
de pé. O que já estava conectado quando ela ligou — o pendrive de boot (label
`NB3CFG`), um leitor de cartão embutido — **não** é reportado; e o mesmo
dispositivo com alerta ainda aberto (um pendrive tirado e recolocado, um
celular que renegocia o MTP a cada minuto) não gera outra linha até alguém
dispensar a primeira. Na Maratona 2026 toda máquina que ficava com o
pendrive de boot espetado aparecia na faixa a cada boot, e a faixa virou
ruído — era uma corrida entre a regra de udev e a label da partição.

A detecção é feita por regra de `udev`, não por varredura: o ciclo de
telemetria é de ~50 segundos e um pendrive espetado por dez segundos passaria
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

Ordem que a máquina não buscou em **10 minutos** caduca (`command_ttl_sec`
em `data/server.json`): máquina desligada não executa a ordem de ontem ao
ligar hoje. Se ela precisava mesmo receber, mande de novo. A ordem caducada
aparece na aba de logs da máquina como `expired`.

### Todas as sedes numa tela

```
https://nutellaboot.mdp.naquadah.com.br/laboratorios/
```

Uma linha por sede — máquinas, quantas rodaram na janela escolhida, quantas
apareceram nela pela primeira vez, quantas estão ligadas, travadas e em alerta.
Clicar na seta expande a sede e mostra as máquinas; clicar na linha seleciona a
sede inteira. A seleção mistura os dois níveis (uma sede inteira e máquinas
soltas de outra) e os comandos valem para o recorte.

Acima de 50 máquinas, confirmar exige **digitar o número** — um clique errado em
"desligar" com a frota selecionada é a prova inteira no chão.

O sub-admin vê só as sedes dele. O botão **Baixar CSV** dá as mesmas contas da
tela, com a janela de dias escolhida.

A imagem de teste dos times (perfil Livre, distribuída publicamente) fica
marcada **"Fora do dashboard"** no `/admin/`: centenas de máquinas de casa
não entram no placar, nas médias nem nos gráficos da frota. O botão ao lado
do perfil liga e desliga a marca.

### Relatório da frota

Na mesma tela, o painel **Relatório da frota** (só administração). Escolha a
janela de dias, clique em *Gerar* e espere: a tela mostra "gerando…" e sozinha
troca para os links quando fica pronto.

Sai um HTML para olhar — perfil nacional de memória e processadores, e por sede
os editores usados, memória, carga, alertas e o que apareceu no dmesg — e os
dados brutos para processar em planilha ou script:

| arquivo | uma linha por |
|---|---|
| `inventario.csv` | máquina (processador, núcleos, RAM, time, organização, país) |
| `editores.csv` | máquina × editor (amostras e minutos acumulados) |
| `recursos-hora.csv` | máquina × hora (memória e carga, média e pico) |
| `recursos-brutos.csv.gz` | amostra (o arquivo grande, comprimido) |
| `alertas.csv` | alerta que tocou, com quem dispensou e quando |

Quanto tempo leva: a frota inteira (1890 máquinas, 25 milhões de amostras) com
7 dias são 1,5 GB lidos e cerca de dois minutos e meio. O resultado dá ~200 MB,
quase tudo no `recursos-brutos.csv.gz`. **Uma geração de cada vez** — duas juntas leriam os
mesmos 1,5 GB em paralelo, e é o mesmo disco que atende o boot das salas. Por
isso também: gere depois da prova, ou num intervalo, e não no meio do início
simultâneo.

Os arquivos ficam em `data/reports/frota/` e são sobrescritos a cada geração.
Se precisar guardar o de uma prova, baixe (ou copie o diretório) antes de gerar
o próximo.

Se o serviço reiniciar no meio da geração, o painel mostra a falha depois de
meia hora e o botão volta a funcionar — a passada não continua de onde parou,
é só pedir de novo.

### Chave de serviço para o MOJ

O juiz consome a API com uma chave `nb3s_` de escopos limitados, criada uma
vez pela administração (`docs/api.md`, seção "Integração com o MOJ"):

```bash
curl -sS -X POST "$SERVER/api/v1/service-keys" -H "Authorization: Bearer $ADMIN_KEY" \
    -H 'Content-Type: application/json' \
    -d '{"name":"moj","scopes":["machines:read","commands:write","alerts:write","bindings:write","roster:read","roster:write","webhooks:write"],"images":["26*"]}'
```

O ideal é **uma chave por evento**, com o glob das imagens daquele evento. A
chave se enxerga (`GET /api/v1/whoami` devolve escopos, globs e as imagens que
eles cobrem), então o MOJ não precisa que ninguém digite os ids das sedes.

#### Webhooks do MOJ: quem instala, para onde apontam e onde ver a falha

Pela tela: na linha da imagem no `/admin/`, **Webhooks** abre a lista da sede
(a do MOJ inclusive): acrescentar, mudar os eventos, trocar o segredo (gerado
no navegador e mostrado uma vez), **Enviar teste** (bate na URL agora e mostra
o status) e as entregas que falharam. Ali também: **Editar** (nome, modelo,
cota de builds), e nas camadas da imagem, **Registrar uma camada já
construída** (o caminho do `nb3-pack-upper`: arquivo em `data/blobs` e md5).
No cartão de publicação, **Publicar** manda um arquivo específico. Em
Pedidos, **Criar a imagem** aprova criando a sede na hora (com id, modelo e
perfil) em vez de emitir um código.

Com `webhooks:write` o próprio MOJ instala e remove o webhook dele
(`POST …/webhooks`, `DELETE …/webhooks/<id>`), sem a chave de administração.
Cada chave só vê e só mexe nos webhooks que criou, e eles só apontam para
`https` de endereço público. Se o receptor estiver numa rede interna, libere o
destino em `data/server.json` (é arquivo de dado, não de código; vale na hora,
sem reiniciar):

```json
{"webhooks": {"allow_hosts": ["moj.interno", "10.1.0.0/16"]}}
```

Quando o MOJ diz que "não recebeu o evento":

1. `POST …/webhooks/<id>/test` manda um `webhook.test` agora e devolve o status
   que o receptor respondeu (ou o erro de conexão).
2. `GET …/webhooks/deliveries` (ou o arquivo
   `data/site-images/<sede>/webhooks.log`) lista as entregas que esgotaram as
   três tentativas: evento, `delivery`, host, caminho e o último status. `error:
   "dropped"` quer dizer que havia entregas demais em voo (receptor morto
   assinando `machine.status`); `forbidden_destination`, que o destino deixou
   de ser público.
3. Peça ao MOJ para **listar os eventos** que quer: `events: []` assina tudo,
   inclusive `machine.status`, dezenas por segundo na frota.

Com `machines:read` ele lê as máquinas (`?active_since=` pula quem não
reportou), as séries em lote (`GET …/site-images/<sede>/samples?since&until&
limit&active_since`, uma linha NDJSON por máquina, com `resampled`,
`native_points` e `interval_s` para saber o que foi reamostrado) e o
relatório. Com `bindings:write` ele publica o elo máquina ↔ time no login
(`PUT …/binding` com `source`, `at` e `boot_id`); o histórico fica em
`GET …/binding/history`.

### Vínculo time ↔ máquina

A visão **Times** do hotconfig faz tudo pela tela: acrescentar um time,
corrigir, tirar, importar uma lista colada ou de arquivo (CSV/TSV com as
colunas `user_id, name, display_name, org_id, org_name, country, seat`, ou
JSON; **Mesclar** acrescenta e atualiza, **Substituir tudo** troca a lista),
exportar, subir o logotipo de cada instituição, e ver quem está sem máquina e
que máquina está sem time. O vínculo se faz na aba **Time** do detalhe da
máquina (busca pelo nome, ou um nome livre para quem não está na lista); mover
um time de uma máquina para outra desfaz o vínculo antigo antes.

O MOJ também escreve aqui (o roster e o vínculo no login do time): a tela mexe
em uma entrada por vez, então os dois convivem. Pela API, o vínculo aponta para
uma entrada do roster:

```bash
curl -X PUT "$SERVER/api/v1/site-images/26spsp/machines/$MAC/binding" \
    -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' \
    -d '{"user_id": "team-001"}'
```

A tela de bloqueio da máquina passa a mostrar o logotipo da instituição, o nome
do time e o lugar. Esses dados são cacheados em disco no
momento do bloqueio: se a rede cair, a tela continua correta.

### Quando uma máquina some do painel

Ela deixa de reportar. Confira, nessa ordem: a máquina está ligada? tem rede?
Se rebootou, ela reaparece com o mesmo MAC e o vínculo continua. Se trocou de
placa de rede, aparece como máquina nova e o vínculo precisa ser refeito.

## 5. Runbook do dia da prova

### Véspera

- [ ] Camada base gerada e registrada no modelo (`nb3-gerar-squash`)
- [ ] `vmlinuz` e `initrd.img` atualizados (`nb3-build-initrd` — ele mesmo
      recusa initrd sem crypto de WPA ou sem os firmwares Intel de wifi)
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

### "NO CONF" numa sala que boota pela rede

O iPXE carregou o kernel e o initrd, mas não o `nutellaboot.conf` com nome. A
linha tem que ser `initrd nutellaboot.conf /nutellaboot.conf` — sem o segundo
argumento o kernel recebe texto onde espera um cpio, e o arquivo não aparece.
O motivo na tela diz `the NB3CFG partition did not show up`: sem o conf, o
initrd não tem como saber que a máquina não usa pendrive. Se a linha estiver
certa, o iPXE da sede é antigo demais para dar nome a um initrd; atualize-o.

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

**A tela `NO WIFI` já diz o motivo.** Ela aparece quando a máquina tentou pelo
rádio e não foi, e traz a razão apurada do próprio `wpa_supplicant`:

| Motivo na tela | O que fazer |
|---|---|
| `refused the password` | a senha no `wifi.conf` foi recusada pelo AP — confira maiúsculas e minúsculas, e o TAB entre nome e senha |
| `requires WPA3 protection (PMF)` | o AP está em modo WPA3/misto exigente; use a rede WPA2 do mesmo roteador ou acrescente uma |
| `was not found on the air` | o nome não apareceu no scan: erro de digitação, rede oculta sem `hidden` no terceiro campo, ou fora de alcance |
| `no address came from DHCP` | conectou, mas o roteador não deu endereço — é problema do DHCP daquela rede, não do pendrive |

Sobre o arquivo: os campos são separados por **TAB**, e a senha do WPA tem de 8
a 63 caracteres (o boot avisa e pula a rede quando não tem). Rede oculta precisa
de `hidden` no terceiro campo. Editar no Windows é seguro — fim de linha, BOM e
espaço sobrando são limpos no boot.

Sem cabo conectado, o rádio é tentado **antes** da rede cabeada: com cabo
espetado num switch morto, a espera do DHCP cabeado é de cinco minutos por
rodada.

**A escada, quando "refused the password" insiste.** Um aviso importante:
`WRONG_KEY` no log **não prova senha errada** — o supplicant carimba isso em
qualquer desconexão no meio da troca de chaves. As duas causas já vistas em
campo que produzem exatamente isso com a senha CERTA:

- **initrd sem os módulos de crypto do kernel** (`ccm`/`cmac`): a chave da
  sessão não instala e o cliente desiste — em qualquer chip, com rede aberta
  funcionando. O boot agora confere sozinho e diz "this initrd was built
  without the WPA crypto modules; rebuild it" — a solução é regerar o initrd
  (`nb3-build-initrd`) e regravar/atualizar o pendrive;
- firmware do rádio cochilando (família MediaTek mt792x; o boot já desliga o
  power-save por conta própria).

E a causa que nem chega ao `WRONG_KEY`, porque sem firmware a interface nem
existe: **initrd sem o firmware do rádio**. A tela diz "the boot image is
missing firmware for this wifi card - contact the organization" — a culpa é
do initrd publicado, não da sede. A solução é da organização: regerar o
initrd (`nb3-build-initrd`, que hoje recusa sair sem os firmwares Intel) e
publicá-lo; as máquinas atualizam o pendrive sozinhas no próximo boot
CABEADO. Uma máquina só-wifi precisa de um boot com cabo ou de um pendrive
regravado a partir do configureitor.

A ordem de ataque:

1. **Confira o tamanho e a impressão digital na tela.** Cada rede aparece como
   `'nome' (password: N chars, fingerprint xxxxxxxx)`. Em qualquer Linux:
   `printf '%s' 'sua-senha' | md5sum` — os 8 primeiros dígitos têm que bater.
   Batem = a senha que chegou é a que você digitou; o problema é adiante.
2. **Troque a senha pela chave derivada.** `wpa_passphrase NOME 'senha'` mostra
   um `psk=` de 64 dígitos hexadecimais; coloque OS 64 DÍGITOS no lugar da
   senha no `wifi.conf` (o boot entende). Se ainda recusar, não é a senha nem a
   derivação — é o rádio ou o AP.
3. **Teste a mesma rede no sistema completo.** Boote por cabo; o NetworkManager
   usa os perfis gerados do MESMO `wifi.conf`, com o mesmo kernel e firmware.
   Conectou lá e não no boot = problema da configuração do initrd; falhou nos
   dois = driver/firmware ou o AP.
4. **`nbwifidebug=y`.** No menu do GRUB, `e` na entrada, acrescente
   `nbwifidebug=y` ao fim da linha do kernel e Ctrl-X. O supplicant roda
   verboso e, na falha, o fim do log sai no console — fotografe.

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

### Máquina parada na tela SEEDING

É de propósito: com `SEEDIMAGE` ligado, a máquina segura o próprio boot no
initrd servindo a imagem para as outras (depois do boot o firewall bloquearia
as conexões), com um relatório ao vivo na tela. Ela sai do modo seed e termina
o boot quando alguém aperta ENTER nela — ou remota e preguiçosamente: remova o
seeder da lista no configureitor e o próximo heartbeat (até 60 s) a libera. O
limite de máquinas semeando ao mesmo tempo é o campo "Limite de semeadores" do
configureitor (padrão 4); quem chega depois do limite boota direto.

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

Primeiro a barra de progresso do hotconfig (ou dos laboratórios): ela diz, por
máquina, quem confirmou, quem espera e quem caducou. A aba **Ordens** do detalhe
da máquina mostra cada confirmação com a saída.

Se a máquina estava desligada quando o comando foi mandado e ligou mais de 10
minutos depois, o comando caducou de propósito (aparece como `expired` na aba
Ordens e em `GET …/commands/{id}`): mande de novo.

O agente fica pendurado numa requisição de até 25 segundos; se a rede oscilar,
ele reconecta e recebe o que ficou pendente — comandos não se perdem, ficam na
fila até serem confirmados. Verifique se a máquina aparece como online no
painel. Se estiver offline, o comando será entregue quando ela voltar.

---

## Capacidade: o que a máquina aguenta

Medido, não estimado — `tools/nb3-carga` simula o ciclo de vida real de N
máquinas (boot, telemetria a cada ~50 s e long-poll contínuo) e mede o que a
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

O reinício leva uns 10 s: o long-poll das máquinas e o SSE dos painéis são
conexões que nunca terminam sozinhas, e o uvicorn as corta depois do
`--timeout-graceful-shutdown 10` da unidade. Máquinas e painéis reconectam
sozinhos. Se o `systemctl restart` demorar 90 s e o journal mostrar `Failed with
result 'timeout'`, a unidade instalada em `/etc/systemd/system/` é a antiga:
refaça o `install` e o `daemon-reload` acima.
