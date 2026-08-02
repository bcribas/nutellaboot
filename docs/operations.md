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
(no caso da maratona, o Maratona Linux do ano).

### 1.1 Criar o template

O **template** é o conjunto de camadas base mais o formulário de configuração
que as sedes vão preencher. As imagens das sedes derivam dele.

```bash
# cria o diretório do template com o esquema padrão de configuração
tools/nb3-seed-testdata          # em ambiente de teste, já cria um pronto
```

Em produção, crie o diretório `data/templates/maratonalinux2604/` com um
`template.json` (lista de camadas, pode começar vazia) e um `schema.json` (o
formulário — copie de outro template ou gere com
`server/app/services/default_schema.py`).

### 1.2 Gerar a camada base

Transforma a imagem-mestre do sistema (por exemplo, o Maratona Linux) num
`.squash` e registra no template:

```bash
sudo tools/nb3-gerar-squash \
    --raw /caminho/ubuntu-24.04-initial.raw \
    --name icpc-latam2026

# ou já publicando no template (precisa da chave de admin):
sudo -E NB3_ADMIN_KEY=nb3a_... tools/nb3-gerar-squash \
    --raw /caminho/ubuntu-24.04-initial.raw \
    --name icpc-latam2026 \
    --register maratonalinux2604 \
    --server https://nutellaboot.naquadah.com.br
```

**Por que sudo:** o comando precisa de `losetup` e `mount` para abrir a
partição raiz de dentro do arquivo `.raw`. É o único motivo.

Demora bastante (a imagem tem alguns GB). No fim ele imprime o md5, que é o que
o boot vai conferir em cada máquina.

### 1.3 Gerar o kernel e o initrd

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

### 1.4 Gravar o pendrive

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

**Não precisa de sudo**: a imagem é montada manipulando o arquivo
(`sfdisk` + `mtools` + `grub2-mkstandalone`), sem `losetup` nem `mount`.

Para gravar no pendrive físico, aí sim:

```bash
sudo dd if=maratona2026.img of=/dev/sdX bs=4M status=progress oflag=sync
```

Depois de gravado, o pendrive é uma partição FAT normal: monte em qualquer
computador e edite `nutellaboot.conf` (sede, chave de boot) e `wifi.conf`
(redes) com um editor de texto.

### 1.5 Publicação de arquivos (files.mdp)

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
identificador, nome e template. A tela devolve, **uma única vez**, o token, a
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
curl -X PATCH https://nutellaboot.naquadah.com.br/api/v1/images/26spsp \
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
```

Ele converte nome, template (inclusive detectando o perfil desbloqueado),
valores de configuração, camadas extras e o wallpaper — se o arquivo estiver na
cópia local do site. Tokens e senhas antigas **não** são importados: a senha de
seeder do nb2 era `md5("qwer <sede>")`, derivável por qualquer pessoa. Cada
imagem recebe credenciais novas, exportadas em CSV.

### Deixar outras pessoas criarem a própria imagem

Nem toda imagem precisa passar por você. Um professor, um laboratório ou uma
instituição pode criar a própria imagem com um **código de convite**. O código
é a credencial: quem o recebe cria sozinho, dentro de uma cota que você define.

**Passo 1 — marque ao menos um template como público.** Só templates públicos
podem ser usados na criação por convite (os templates de prova bloqueados ficam
privados, fora do alcance de terceiros). No `/admin/`, na seção de templates,
clique em "Tornar público". Ou pela API:

```bash
curl -X PATCH "$SERVER/api/v1/templates/generico" \
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
    -d '{"count": 10, "max_images": 1, "build_quota": 5}'
```

Cada código sai no formato `NB3-XXXX-XXXX`. Os campos: `count` (quantos códigos
gerar), `max_images` (quantas imagens o código cria, padrão 1), `build_quota`
(quantas camadas de pacotes cada imagem criada pode construir, padrão 5),
`template` (opcional — fixa o template, senão a pessoa escolhe entre os
públicos) e `expires_at` (opcional, epoch). Entregue o código por um canal
privado.

**Passo 3 — a pessoa cria.** Ela abre `/criar/`, na aba "Tenho um código de
convite", cola o código, escolhe um nome (que **não** pode começar com dígito),
um nome de exibição e o template público. Ao criar, a tela devolve — **uma
única vez** — o token, a chave de boot, a chave de máquina e os links prontos do
configureitor e do painel. A partir daí ela cuida da própria imagem, e pode até
instalar pacotes extras (ver [layer-builds.md](layer-builds.md)), dentro da
cota do código.

Para revisar ou revogar códigos, use a lista na seção Convites do `/admin/` (o
botão "Revogar") ou `DELETE /api/v1/invites/<código>`.

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
- **Namespace reservado.** Nomes começando com dígito são recusados na criação
  por convite — continuam só da administração.
- **Templates públicos, só os marcados.** Quem é de fora nunca parte de um
  template de prova bloqueado.
- **Limite de taxa por IP.** As rotas públicas (`/api/v1/public/images` e
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
curl https://nutellaboot.naquadah.com.br/api/v1/templates/maratonalinux2604/schema \
    -H "Authorization: Bearer $NB3_ADMIN_KEY"

# abrir a RAM mínima e fechar o fuso horário
curl -X PUT https://nutellaboot.naquadah.com.br/api/v1/templates/maratonalinux2604/schema/locks \
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

Quais campos são obrigatórios em cada perfil é decisão do **template** (campos
marcados `locked` no `schema.json`), não da imagem. Ou seja: dá para ter um
template de prova rígido e um template de laboratório mais frouxo.

### Wallpaper: agora é upload

Não existe mais campo de URL. A pessoa escolhe o arquivo (PNG ou JPEG) e clica
em enviar; o servidor guarda, calcula o md5 e passa a servir para as máquinas.

No NutellaBoot 2 era uma URL colada à mão. O servidor baixava a imagem **na
hora de salvar**, e uma URL ruim derrubava o salvamento inteiro da
configuração. Pior: na máquina, o download do wallpaper acontecia no boot e,
quando falhava, parava num `Continue anyway? (Y/n)` esperando alguém digitar.
Hoje, falha de wallpaper só registra um aviso e o boot segue.

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

O cartão mostra o time vinculado, o lugar, uso de memória, carga e estado do
firewall. Clique duplo abre o detalhe com a telemetria completa.

Filtros rápidos: todas, bloqueadas, em alerta, sem time, offline.

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
curl -X PUT "$SERVER/api/v1/images/26spsp/machines/$MAC/binding" \
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

- [ ] Camada base gerada e registrada no template (`nb3-gerar-squash`)
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
curl "$SERVER/api/v1/images/26spsp/boot-key" -H "Authorization: Bearer $NB3_ADMIN_KEY"
```

Se alguém rodou `boot-key/rotate`, **todos** os pendrives daquela imagem
precisam ser atualizados.

### "Nenhum disco utilizável"

O boot precisa de uma partição ext3/ext4/NTFS gravável com pelo menos ~14 GB
livres, para o cache das camadas e a home persistente. Se a máquina só tem
NTFS, o motivo mais comum é o Windows ter sido "desligado" com Fast Startup
ligado: o sistema de arquivos fica marcado como em uso. Faça um desligamento
completo (Shift + Desligar) e tente de novo.

O boot imprime na tela um relatório de cada partição encontrada e por que foi
recusada.

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
curl "$SERVER/api/v1/images/26spsp/seeders" -H "Authorization: Bearer $TOKEN"
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
