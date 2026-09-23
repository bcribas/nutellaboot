# Camadas extras (pacotes adicionais)

Não é raro precisar de um pacote a mais numa imagem: um compilador de linguagem
específica, um simulador, uma IDE. Este documento explica como isso é
atendido — e por que o caminho mudou.

Há dois caminhos para pedir a construção: o da **administração**, que constrói
para qualquer imagem sem limite; e o do **dono de uma imagem**, que constrói
para a própria imagem dentro de uma cota (é o que permite a quem criou uma
imagem por convite instalar seus próprios pacotes). Os dois usam o mesmo worker
sem root descrito abaixo.

## Pela interface

O jeito normal de pedir uma camada é pelo `/admin/`, sem tocar em `curl`. Há
dois pontos de partida.

**Para um modelo** (aba **Camadas**, ou a seção **Camadas** da página do
modelo): **Construir camada**. Preencha o nome da camada, escolha o modelo e
liste os pacotes (separados por espaço ou vírgula). Os pacotes são instalados
por cima das camadas daquele modelo. Se quiser, marque as imagens do modelo em
que ela deve entrar quando ficar pronta. É o caminho para quando várias sedes
precisam do mesmo pacote: uma construção só.

**Para uma imagem só** (seção **Camadas** da página da imagem): **Construir
camada**, com o nome e os pacotes. A camada nasce destinada àquela imagem e
entra nela sozinha quando fica pronta.

O pedido entra numa fila, e a aba **Camadas** mostra o andamento, atualizando
sozinha enquanto houver construção em curso:

| Estado | O que significa |
|---|---|
| na fila | aguardando o worker pegar |
| construindo | rodando o `apt` dentro do sandbox |
| pronta | camada gerada, com arquivo, tamanho e md5 |
| falhou | erro na construção; a mensagem aparece ao lado |

Cada construção pronta mostra o arquivo, o tamanho, o **md5** (com botão de
copiar) e **onde está**: no modelo, em quais imagens, ou "ainda não anexada".

**Anexar** é o passo que faz a camada entrar no boot. O diálogo oferece:

- **o modelo inteiro** em que ela foi construída. Vale para todas as imagens
  dele, inclusive as criadas depois, e é o que quase sempre se quer. Só quem
  gerencia o modelo marca essa opção;
- **imagens**, uma a uma. As de outro modelo aparecem com um aviso: a camada
  leva o estado do `apt` da base em que foi construída.

O **Anexar camada** das páginas de modelo e de imagem faz o mesmo a partir de
uma lista: as camadas em uso e as construções prontas, com o md5 junto (ou à
mão, com arquivo e md5, para uma camada feita pelo `nb3-pack-upper`). Na página
de outro modelo a tela avisa antes de anexar uma construção feita sobre outra
base. Uma construção cujo arquivo sumiu (nem no disco, nem publicado) aparece
com o **Anexar** desabilitado.

A página da imagem, seção **Camadas**, mostra o que as máquinas dela baixam, na
ordem do manifest: as camadas próprias da imagem (com **Remover**) e as que vêm
do modelo, cada uma com papel e md5. Ali também estão as construções daquela
imagem e quantas ela já usou da cota. A página do modelo mostra, além das
camadas dele, as que só algumas imagens do modelo têm: era a falta disso que
fazia a camada "aparecer na imagem e não no modelo".

Ao terminar, a camada é **publicada no servidor de arquivos** e é de lá que as
máquinas baixam. Se a publicação falhar (servidor fora do ar, por exemplo), a
camada continua servida pela própria máquina de gestão (o boot não quebra), e a
seção **Publicação de arquivos**, na aba **Sistema**, oferece **Reenviar
pendentes**. Veja a seção de publicação em `docs/operations.md`.

## O problema que isto resolve

No NutellaBoot 2, atender a esse pedido era um processo manual de vários
passos:

1. subir a máquina virtual de teste (`rodar-nutellatest`);
2. fazer login e instalar o pacote com `apt`;
3. dar `tar` em `/dev/newroot/upper` — a camada de escrita do overlay, que
   fica **em memória**;
4. tirar o tar de dentro da VM;
5. podar o lixo à mão: cache do apt, logs, `/tmp`, arquivos de dispositivo,
   credenciais;
6. rodar `mksquashfs`;
7. calcular o md5 e copiar do terminal;
8. editar o `template.extra` da sede no servidor, colando md5 e nome.

(Aquele campo se chamava `template.extra` no NutellaBoot 2; hoje o conceito
equivalente é a lista de camadas do **modelo**.)

Cada passo dependia de alguém lembrar. Na prática, a poda variava muito: uma
camada foi publicada com `/tmp` inteiro dentro; outra ainda tinha `/etc/shadow`
com o hash real da senha de root. E o passo 8, feito à mão, produzia linhas com
a URL literal `unk` quando ninguém preenchia o campo.

> **Este documento é sobre camadas EXTRA** — pacotes por cima do sistema. A
> **camada base** (o sistema operacional inteiro) é outra coisa e se gera de
> outro jeito: `tools/nb3-gerar-squash` a partir da imagem-mestre `.raw`, com
> o roteiro completo em [operations.md](operations.md), seção 1.

## O caminho automático

Você pede os pacotes; o servidor constrói, poda e registra.

```bash
curl -X POST "$SERVER/api/v1/layerbuilds" \
    -H "Authorization: Bearer $NB3_ADMIN_KEY" \
    -H 'Content-Type: application/json' \
    -d '{
          "name": "linguagens-extras",
          "model": "maratonalinux2604",
          "packages": ["ghc", "sbcl", "fp-compiler"],
          "attach_to": ["26spsp"]
        }'
```

Isso devolve um `id` de job. O trabalho fica numa fila em disco
(`data/layerbuilds/queue/`), e quem constrói é o worker:

```bash
tools/nb3-layer-worker            # fica observando a fila
tools/nb3-layer-worker --once     # processa o que houver e sai
```

Um **sub-admin** também pode pedir build, com a mesma rota e o código de
convite como credencial: só nos modelos que ele administra e nas imagens dele,
gastando a `build_quota` do convite. A cota conta **tentativas**, não sucessos
— senão uma fila de builds quebrados sairia de graça.

Acompanhe pelo id:

```bash
curl "$SERVER/api/v1/layerbuilds/<id>" -H "Authorization: Bearer $NB3_ADMIN_KEY"
```

A resposta traz o estado (`queue`, `running`, `done`, `failed`), o log da
construção e, quando termina, o arquivo gerado com md5 e tamanho.

Nomes de pacote são validados antes de entrar na fila: só
`[a-z0-9][a-z0-9+._-]*`. Não há como injetar opção de linha de comando nem
`;` no meio do nome.

### Sem root, de verdade

O worker roda como usuário comum. Nada de `sudo`:

| Ferramenta | Papel |
|---|---|
| `unshare --user --map-auto --map-root-user` | cria um namespace onde somos "root" |
| `squashfuse` | monta cada camada base, só leitura |
| `fuse-overlayfs` | junta as camadas com uma área de escrita real em disco |
| `bwrap` | entra no sistema montado para rodar o `apt` |
| `mksquashfs` | empacota só a diferença, já podada |

Detalhe que importa para quem for mexer: **montagem, apt, poda e mksquashfs
rodam todos dentro do mesmo namespace**. Os arquivos criados pelo `apt`
pertencem ao "root" daquele namespace — visto de fora, um subuid — e do lado de
fora nem dá para apagá-los. Por isso o worker se re-executa com `--build-job`
lá dentro.

### A poda automática

Removido sempre:

```
var/cache/apt              var/lib/apt/lists          var/log
tmp                        run                        root/.bash_history
root/.cache                etc/resolv.conf            etc/hostname
etc/machine-id             usr/sbin/policy-rc.d       var/lib/dbus/machine-id
etc/.nb3                   etc/.secrets
```

Mais os padrões `var/lib/dpkg/*-old`, `**/*.dpkg-new`, `**/*.dpkg-tmp`, e todos
os arquivos de dispositivo (os "whiteouts" do overlay não fazem sentido numa
camada publicada).

Tratamento especial para credenciais — `etc/shadow`, `etc/gshadow`,
`etc/shadow-`, `etc/gshadow-`, `etc/passwd-`, `etc/group-`:

- os arquivos de backup (terminados em `-`) são apagados;
- nos demais, **todo hash de senha é substituído por `*`**.

Ou seja: se o pacote criar um usuário de sistema (é comum — `openssh-server`,
bancos de dados), o usuário entra na camada com a conta **bloqueada**, nunca
com o hash. Isso é verificado por teste automatizado
(`tests/test_layer_builder.py`), que constrói uma camada de mentira com um hash
plantado e falha se ele aparecer no `.squash`.

### Anexar ao modelo ou a imagens

Se você não passou `attach_to` na criação, anexe depois:

```bash
# ao modelo em que foi construída: todas as imagens dele, inclusive as futuras
curl -X POST "$SERVER/api/v1/layerbuilds/<id>/attach" \
    -H "Authorization: Bearer $NB3_ADMIN_KEY" \
    -H 'Content-Type: application/json' \
    -d '{"model": true}'

# a imagens escolhidas
curl -X POST "$SERVER/api/v1/layerbuilds/<id>/attach" \
    -H "Authorization: Bearer $NB3_ADMIN_KEY" \
    -H 'Content-Type: application/json' \
    -d '{"image_ids": ["26spsp", "26mgbh"]}'
```

`model: true` é sempre o modelo do job: o worker instalou os pacotes por cima
das camadas dele, e o estado do `apt` da camada só confere com aquela base. A
camada entra na frente das outras, com papel `extra`. Os dois campos podem ir
juntos, e o corpo vazio usa o `attach_to` do pedido. Nada é gravado se alguma
permissão falhar, e uma construção cujo arquivo sumiu responde `409`.

Uma camada que está no modelo **e** numa imagem dele aparece uma vez só no
manifest daquela imagem.

Para remover de uma imagem:

```bash
curl -X DELETE "$SERVER/api/v1/site-images/26spsp/layers/<arquivo.squash>" \
    -H "Authorization: Bearer $NB3_ADMIN_KEY"
```

Para ver o que a imagem tem hoje:

```bash
curl "$SERVER/api/v1/site-images/26spsp/layers" -H "Authorization: Bearer $TOKEN"
```

## O dono da imagem constrói a própria camada (com cota)

Quem criou uma imagem por código de convite pode instalar seus próprios
pacotes, sem chave de administração. A rota é por imagem e aceita o **token da
imagem** (o mesmo do configureitor):

```bash
curl -X POST "$SERVER/api/v1/site-images/meu-lab/layerbuilds" \
    -H "Authorization: Bearer $TOKEN_DA_IMAGEM" \
    -H 'Content-Type: application/json' \
    -d '{"name": "meus-extras", "packages": ["htop", "tmux"]}'
```

Diferenças em relação ao caminho da administração:

- **Cota por imagem.** Pelo token, cada imagem só constrói até `build_quota`
  camadas (padrão 5, herdado do código de convite que a criou). A conta soma
  todas as tentativas, inclusive as que falharam. Estourou, a resposta é `403`,
  e a pessoa pede à administração para aumentar. A administração não tem cota.
- **Pelo console, a cota é da pessoa.** O sub-admin que constrói pela página
  da imagem gasta a cota de construções do convite dele, a mesma da construção
  por modelo, e o job leva o dono. Antes, a rota por imagem dispensava a cota
  do sub-admin.
- **Anexação automática.** Não é preciso `attach_to` nem um passo de
  `/attach`: a camada nasce marcada para esta imagem, e o worker a anexa
  sozinho quando termina (camada extra, portanto com prioridade no overlay).
- **Escopo fechado.** A camada só pode ir para a própria imagem; o token de uma
  imagem não constrói nem anexa em outra.

Acompanhe o andamento (dono ou administração):

```bash
curl "$SERVER/api/v1/site-images/meu-lab/layerbuilds" \
    -H "Authorization: Bearer $TOKEN_DA_IMAGEM"
```

### Risco residual, e o que fazer com ele

Deixar terceiros instalarem pacotes significa que o `apt` roda **no seu
servidor**, a pedido de gente que você não conhece, buscando pacotes dos
repositórios do Ubuntu. Isso é uma superfície real; a contenção é em camadas:

- **cota por imagem** limita o volume por pessoa;
- **um build por vez** — o worker processa a fila em série, então nem uma
  rajada de pedidos vira uma rajada de `apt` simultâneos;
- **nome de pacote validado** (`[a-z0-9][a-z0-9+._-]*`) — não há como injetar
  opção de linha de comando nem `;`;
- **sandbox sem root** com a poda automática descrita abaixo, que também impede
  a camada de levar embora credenciais.

Mesmo assim, **monitore**. Os jobs ficam visíveis em
`data/layerbuilds/{queue,running,done,failed}/` e em `GET /api/v1/layerbuilds`
(administração). Se um código ou uma imagem estiver abusando, você pode revogar
o convite (aba **Pessoas** do `/admin/`, ou `PATCH /api/v1/invites/<código>`
com `{"revoked": true}`), que fecha o console e a criação de imagens, e zerar,
na prática, a construção baixando a cota: a da pessoa, na página dela, e a da
imagem, na seção **Geral** da página da imagem. Como a cota conta todas as
tentativas, uma cota abaixo do já usado bloqueia novos builds na hora.

## Pré-requisitos do host

```bash
tools/nb3-layer-worker --check
```

Se faltar algo, ele diz o quê. No Fedora:

```bash
sudo dnf install bubblewrap squashfuse fuse-overlayfs squashfs-tools
```

Além das ferramentas, o usuário precisa de faixa de subuid/subgid — é o que
permite o namespace mapear vários UIDs:

```bash
grep "^$USER:" /etc/subuid /etc/subgid
# esperado, por exemplo:
# /etc/subuid:ribas:524288:65536
# /etc/subgid:ribas:524288:65536
```

Se não houver, `sudo usermod --add-subuids 524288-589823 --add-subgids
524288-589823 $USER` (uma vez só, e é a única coisa nesse fluxo que pede root).

## O caminho alternativo, pela máquina virtual

Use quando a mudança precisa acontecer no ambiente real de boot: driver que só
carrega com o hardware montado, banco dconf compilado, algo que dependa do
sistema em execução e não apenas do `apt`.

**Na máquina (ou VM) já bootada pelo NutellaBoot**, depois de instalar o que
quiser:

```bash
sudo nb3-capture-upper /secretdev/nutellaboot/minha-camada.tar
```

Ele copia a camada de escrita do overlay, aplica **a mesma poda** do builder
automático (incluindo o bloqueio dos hashes de senha) e empacota.

**No seu computador**, transformando em camada e publicando:

```bash
tools/nb3-pack-upper minha-camada.tar \
    --name spim \
    --attach 26spsp \
    --server https://nutellaboot.mdp.naquadah.com.br \
    --admin-key nb3a_...
```

O `nb3-pack-upper` repete a poda de credenciais como rede de segurança, mesmo
que a captura tenha sido feita à mão. Sem `--attach`, ele apenas gera o
`.squash` e imprime o md5, para você anexar quando quiser.

## Como a camada entra no boot

O manifest que a máquina baixa lista as camadas nesta ordem:

```
<camadas extras da imagem>     ← primeiro
<camadas do modelo>           ← depois (a base)
```

E o overlayfs monta na mesma ordem, o que significa: **camada extra tem
prioridade**. Um arquivo presente na camada extra sobrepõe o mesmo arquivo da
imagem base. É como se sobrepõe um wallpaper, uma configuração ou uma versão
diferente de um binário.

É a mesma semântica do `template.extra` do NutellaBoot 2 — a diferença é que
agora a ordem é garantida pelo servidor, e não por quem editou o arquivo por
último.

Anexar a mesma camada duas vezes não duplica: o registro substitui a entrada
anterior de mesmo nome de arquivo.

As camadas construídas localmente ficam em `data/blobs/` e são servidas em
`/blobs/<arquivo>`. O md5 vai no manifest, e a máquina confere depois de
baixar — camada corrompida no caminho é descartada e baixada de novo.

## Acompanhar pela tela

Cada construção, na aba **Camadas** do `/admin/` e na página da imagem, tem
**Log**: abre os últimos 8000 caracteres da saída e acompanha sozinho enquanto o
build está na fila ou rodando. Antes só apareciam os primeiros 80 caracteres do
erro, e um build que falhava era um beco sem saída na interface.
