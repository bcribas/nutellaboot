# Como verificar que está funcionando

Três níveis de verificação, do mais rápido ao mais completo: a suíte de testes,
o servidor local com `curl`, e o boot de verdade numa máquina virtual.

Todos os comandos partem da raiz do repositório (`nutellaboot3/`).

## 1. A suíte de testes

```bash
.venv/bin/python -m pytest
```

Roda em poucos segundos. O que cada arquivo cobre:

| Arquivo | O que garante |
|---|---|
| `test_fsdb.py` | escrita atômica e travas do banco-filesystem; dois escritores concorrentes não perdem dados |
| `test_auth.py` | as classes de credencial (admin, imagem, serviço, máquina) e seus limites |
| `test_health.py` | o endpoint de saúde |
| `test_boot_endpoints.py` | manifest com todos os seeders vivos e o CDN por último, TTL de seeder, geração do stuff, chave de boot, criação e criação em massa de imagens |
| `test_bootstrap_shell.py` | a lógica shell do initrd: precedência de configuração, geração do `wpa_supplicant.conf`, pin de `/etc/hosts`. Inclui três testes de regressão que **falham se alguém**: usar `read` interativo no caminho de boot, desligar a verificação de certificado, ou redefinir as funções de rede dentro do stuff |
| `test_config.py` | validação do formulário, campos bloqueados, senha guardada só como hash, upload de wallpaper |
| `test_commands.py` | ciclo de vida do comando (enfileirar, buscar, confirmar), lista de comandos permitidos, bloqueio de tela, teto de tamanho dos logs |
| `test_longpoll_async.py` | a latência real do long-poll no mesmo event loop: bloqueio chega em menos de 1,5 s, e 50 máquinas simultâneas em menos de 3 s |
| `test_roster_sse.py` | roster, vínculo time↔máquina, dados da tela de bloqueio, e que esses dados não vazam segredo |
| `test_moj_webhooks.py` | chaves de serviço com escopo, filtro por imagem, e entrega de webhook assinado a um receptor real |
| `test_layer_builder.py` | construção de camada **sem root**, ponta a ponta, com poda verificada — inclusive que nenhum hash de senha sai na camada |
| `test_i18n_locales.py` | os três idiomas têm exatamente as mesmas chaves, sem valores vazios, e toda chave usada nas páginas existe |
| `test_live_server.py` | sobe um `uvicorn` de verdade e testa SSE e latência de bloqueio por HTTP |

Sobre o `test_live_server.py`: ele existe porque o transporte ASGI do `httpx`
**não** faz streaming — executa a aplicação até o fim antes de devolver a
resposta, o que deixaria um fluxo SSE (que não termina) pendurado para sempre.
A única forma honesta de testar SSE é contra um servidor real.

O `test_layer_builder.py` é pulado automaticamente se as ferramentas rootless
não estiverem instaladas (veja `docs/layer-builds.md`).

## 2. O ambiente local

```bash
tools/nb3-seed-testdata     # cria chave de admin, template e a imagem testes3
tools/nb3-dev               # sobe o servidor em 127.0.0.1:8890
```

O `nb3-seed-testdata` imprime as credenciais **uma vez**: chave de
administração, token, chave de máquina e chave de boot da imagem `testes3`.
Anote. Ele é idempotente — rodar de novo não sobrescreve o que já existe.

O `nb3-dev` sobe um único worker. Isso não é detalhe de configuração: o
long-poll e o SSE mantêm os sinais de acordar em memória, então **mais de um
worker quebraria a entrega de comandos**.

Já existe um proxy nginx apontando para esse servidor:

```
https://nutellaboot.charge.naquadah.com.br:8443  →  localhost:8890
```

Use o endereço público quando quiser testar com TLS de verdade (é o que as
máquinas usam) e o `localhost` para depurar sem passar pelo proxy.

### Verificação por curl

```bash
B=https://nutellaboot.charge.naquadah.com.br:8443
BK=nb3b_...          # chave de boot de testes3
TK=nb3i_...          # token da imagem
AK=nb3a_...          # chave de administração

# saúde do serviço
curl -s "$B/api/v1/health"

# o que o initrd checa antes de tudo
curl -s "$B/boot/v3/sanity"          # deve responder: penguin
curl -s "$B/boot/v3/time"            # hora do servidor, em segundos

# lista de camadas (precisa da chave de boot)
curl -s "$B/boot/v3/testes3/manifest" -H "X-NB-Boot-Key: $BK"

# o script de boot, montado na hora
curl -s "$B/boot/v3/testes3/stuff" -H "X-NB-Boot-Key: $BK" | head -20

# sem a chave, o servidor recusa
curl -s -o /dev/null -w '%{http_code}\n' "$B/boot/v3/testes3/manifest"   # 401

# configuração da imagem (token da imagem)
curl -s "$B/api/v1/images/testes3/config" -H "Authorization: Bearer $TK"

# listagem de imagens (chave de administração)
curl -s "$B/api/v1/images" -H "Authorization: Bearer $AK"
```

Vale conferir que o `stuff` gerado é shell válido antes de mandar para uma
máquina:

```bash
curl -s "$B/boot/v3/testes3/stuff" -H "X-NB-Boot-Key: $BK" > /tmp/stuff.sh
sh -n /tmp/stuff.sh && echo "sintaxe ok"
```

A documentação das rotas fica em `$B/api/v1/docs` (OpenAPI, gerado
automaticamente).

## 3. Boot em máquina virtual

```bash
tools/nb3-run-test
```

Ele gera o pendrive de teste (sem root), cria um "disco da máquina" de 40 GB
esparso se ainda não existir, e sobe o qemu em UEFI com os dois discos. Opções
úteis:

| Opção | Efeito |
|---|---|
| `--image 26spsp` | outra imagem |
| `--server URL` | outro servidor |
| `--fresh-disk` | descarta o disco e começa do zero |
| `--build-only` | só gera o pendrive, não sobe a VM |
| `--headless` | sem janela gráfica |

### O detalhe do `10.0.2.2`

Dentro do qemu com rede de usuário (SLIRP), a máquina hospedeira é sempre
`10.0.2.2`. Além disso, o nome do servidor de teste resolve **apenas em IPv6**,
e o SLIRP é IPv4 — a máquina virtual não conseguiria chegar nele por DNS.

Por isso o `nb3-run-test` grava no `nutellaboot.conf` do pendrive de teste:

```
NB_HOSTS=nutellaboot.charge.naquadah.com.br 10.0.2.2
```

Isso escreve a linha no `/etc/hosts` do initrd. O nome continua o mesmo — muda
só o endereço — então **o certificado continua sendo validado normalmente**.
Não há exceção de TLS no ambiente de teste.

O `aria2c` roda com `--async-dns=false` justamente para honrar esse
`/etc/hosts`; com o resolvedor assíncrono ele ignoraria o arquivo.

### Screenshot sem olhar a tela

```bash
tools/nb3-qemu-shot data/test-usb.img /tmp/tela.png --wait 8
```

Sobe a imagem no qemu, espera os segundos indicados, tira um screenshot e
encerra. É como se verifica que o pendrive dá boot sem precisar de hardware nem
de alguém olhando. Com `--disk` você anexa o disco da máquina, e com `--keep` a
VM continua rodando depois do screenshot.

Momentos úteis para capturar:

| Espera | O que deve aparecer |
|---|---|
| ~6 s | o menu do GRUB com as quatro entradas |
| ~45 s | "Booting…" e as primeiras mensagens do kernel |
| ~3 min | o initrd baixando as camadas (depende da rede) |

### O que verificar num boot completo

1. o menu do GRUB aparece e a entrada padrão inicia;
2. a mensagem "PODE RETIRAR O PENDRIVE AGORA" aparece cedo;
3. a rede sobe e o `sanity` responde (sem erro de certificado);
4. as camadas são baixadas e o md5 confere;
5. o sistema chega à tela de login;
6. a máquina aparece no painel `/hotconfig/`;
7. bloquear pelo painel acende o cadeado no cartão e a tela muda na VM em
   poucos segundos;
8. matar o processo da tela na VM: ela volta em até 3 segundos;
9. a senha de emergência destrava.

## 4. A tela de bloqueio

Os três temas podem ser vistos no navegador, sem máquina nenhuma:

```
http://127.0.0.1:8890/lock/
```

A página mostra `clássico`, `animado` e `minimalista` lado a lado, com dados de
exemplo, e cada um pode ser aberto em tela cheia. É o que a pessoa escolhe no
campo "Tema da tela de bloqueio" do configureitor.

Para testar com dados reais de um time, abra um tema direto passando o mesmo
formato que o `maratona-wait` usa:

```
/lock/themes/animado/index.html?lang=pt&info=<JSON codificado com encodeURIComponent>
```

Mexa o mouse ou digite: o aviso "NÃO mexa no mouse nem no teclado" aparece nos
três idiomas e escala visualmente se o toque continuar.

Os temas usam script clássico (`<script src=…>`), não módulos ES. Isso não é
estilo: os temas são carregados de `file://` dentro do WebKit, e imports de
módulo são bloqueados por CORS nesse esquema — a tela abriria em branco na
máquina do competidor.
