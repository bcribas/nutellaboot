# Manual de operação

Este é o documento do dia a dia: preparar a temporada, criar as imagens das
sedes, entregar a configuração para as pessoas e conduzir a prova.

Todos os comandos assumem que você está na raiz do repositório
(`nutellaboot3/`). Onde precisa de `sudo`, está dito por quê.

## 1. Preparar a temporada

Isso se faz uma vez por ano, quando sai a nova imagem do Maratona Linux.

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

Transforma a imagem-mestre do Maratona Linux num `.squash` e registra no
template:

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

## 2. Criar as imagens das sedes

### Namespace reservado

Nomes que **começam com dígito** são reservados à administração da maratona.
É a convenção do ano: `26brbr`, `26spsp`, `26mgbh`. O servidor marca essas
imagens como `contest`; as demais (`ifsp`, `unb-apc`, `curso-algoritmos`) ficam
como `personal` e são as que você entrega para professores e instituições.

A regra está em `data/server.json` (`reserved_prefix_regex`), e a criação é
sempre feita por quem tem chave de administração — o namespace existe para
deixar claro, na listagem, o que é oficial e o que é de terceiros.

### Uma de cada vez

Abra `/admin/` no navegador, informe a chave de administração e preencha
identificador, nome e template. A tela devolve, **uma única vez**, o token, a
chave de máquina, a chave de boot e o link de configuração. Copie tudo antes de
sair da página.

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

## 3. Entregar a configuração para as pessoas

Cada imagem tem um link próprio:

```
https://nutellaboot.naquadah.com.br/configureitor/?id=26spsp&tk=nb3i_...
```

Esse link **é** a credencial: quem tem o link configura a imagem. Mande por
canal privado. Se vazar, gere outro em `/admin/` ("Gerar novo token").

A página funciona em português, inglês e espanhol — o idioma é detectado pelo
navegador e pode ser trocado no canto superior direito.

### O que a pessoa pode configurar

| Campo | O que faz |
|---|---|
| Login automático | entra direto no usuário `icpc` (bloqueado: obrigatório na maratona) |
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
pela organização da maratona": são as decisões que não podem variar por sede.
Só a administração muda — ou imagens marcadas como `unlocked`, que é o
equivalente ao antigo perfil "-desbloqueado".

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
