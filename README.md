# NutellaBoot 3

Sistema de boot em rede da **Maratona SBC de Programação**. Um pendrive de
400 MB liga a máquina, e ela baixa o Maratona Linux inteiro do servidor,
monta em camadas e entrega o ambiente de prova pronto — com telemetria,
bloqueio de tela remoto e configuração por sede.

É a terceira geração do sistema. As duas anteriores rodaram por anos em
dezenas de sedes; esta reescreve o servidor em Python, enxuga o cliente e
fecha as pontas soltas que doíam na operação.

```
pendrive              servidor                         máquina da sala
┌──────────┐  TLS   ┌──────────────┐               ┌────────────────────┐
│ GRUB     │───────▶│ /boot/v3     │  script de    │ overlayfs:         │
│ kernel   │        │  manifest    │  boot +       │  camadas extras    │
│ initrd   │◀───────│  stuff       │  lista de     │  + firefox         │
│ conf     │        │              │  camadas      │  + wifi            │
└──────────┘        │ /api/v1      │◀──telemetria──│  + Maratona Linux  │
   (sai cedo)       │  máquinas    │───comandos───▶│                    │
                    │  bloqueio    │   (<2 s)      └────────────────────┘
                    └──────────────┘
```

## O que mudou em relação ao NutellaBoot 2

| Assunto | Antes | Agora |
|---|---|---|
| Servidor | CGI em bash, roteado por `PATH_INFO` | API REST em FastAPI, com OpenAPI |
| Seeders | sorteio de **um** servidor por boot; seeder morto travava 1/N dos boots | manifest devolve **todos** os seeders vivos + CDN; o aria2c contorna sozinho |
| Comandos | polling de 5–30 s + atraso configurado: passava de 30 s | long-poll: chega em **menos de 2 s**, com ~1 requisição por máquina a cada 25 s |
| Endpoints de boot | abertos; bastava saber o nome da sede | **chave de boot** no pendrive, enviada por POST |
| TLS | `--check-certificate=false` em todo download | certificado validado sempre, com acerto de relógio antes |
| WiFi | existia no initrd, mas o script servido nunca o ligava | conecta e **espera a associação**; o mesmo `wifi.conf` gera os perfis do sistema |
| Pendrive | ~45 imagens de 400 MB, diferindo em um token | uma imagem genérica + um arquivo de texto editável; gerada **sem root** |
| Wallpaper | URL colada à mão; falha derrubava o salvamento e travava o boot | upload do arquivo; falha no boot só registra e segue |
| Pacotes extras | subir VM, instalar, `tar` do overlay em RAM, podar à mão, `mksquashfs`, editar arquivo no servidor | uma chamada de API; worker **sem root** com poda automática |
| Tela de bloqueio | página remota, prefixo da sede fixo no código, `pkill` destravava | temas locais, dados do time em cache, relança sozinha, senha de emergência |
| Configuração travada | dois diretórios de template mantidos em paralelo | um campo `locked` no esquema |
| Idiomas | só inglês | português, inglês e espanhol em todas as telas |

## Começando

```bash
cd nutellaboot3
python3 -m venv .venv && .venv/bin/pip install -e .   # ou: pip install fastapi uvicorn[standard] python-multipart httpx
tools/nb3-seed-testdata      # cria a chave de admin, um template e a imagem 'testes3'
tools/nb3-dev                # sobe em http://127.0.0.1:8890
```

Verificando:

```bash
curl http://127.0.0.1:8890/api/v1/health
curl -X POST --data "key=$(cat data/images/testes3/boot.key)" \
     http://127.0.0.1:8890/boot/v3/testes3/manifest
```

Telas: `/admin/` (imagens e credenciais), `/configureitor/?id=…&tk=…`
(configuração da sede), `/hotconfig/?id=…&tk=…` (painel do laboratório),
`/lock/` (temas da tela de bloqueio), `/api/v1/docs` (API navegável).

## Mapa do repositório

```
server/app/          API FastAPI: routers/ (rotas) e services/ (regras + acesso a disco)
client/
  initramfs-tools/   o initrd: bootstrap de rede, wifi e TLS
  stuff/             o script de boot, em módulos, montado e servido pela API
  telemetry/         agente, tela de bloqueio (GJS) e temas
  usb/               exemplos de nutellaboot.conf e wifi.conf
web/                 telas em JavaScript puro, trilíngues
tools/               tudo que se roda na mão (ver abaixo)
docs/                documentação (comece por docs/operations.md)
tests/               105 testes: pytest
data/                o estado do servidor (não versionado)
```

## Ferramentas

| Comando | Para quê | Precisa de root? |
|---|---|---|
| `nb3-dev` | sobe o servidor de desenvolvimento | não |
| `nb3-seed-testdata` | cria dados de teste | não |
| `nb3-genusb` | gera a imagem do pendrive | **não** |
| `nb3-run-test` | sobe uma VM que boota pelo servidor | não |
| `nb3-qemu-shot` | tira screenshot do boot da VM | não |
| `nb3-layer-worker` | constrói camadas extras (pacotes) | **não** |
| `nb3-capture-upper` / `nb3-pack-upper` | camada pelo caminho da VM | não |
| `nb3-bulk-create` | cria dezenas de imagens de um TSV | não |
| `nb3-import-nb2` | importa as imagens do NutellaBoot 2 | não |
| `nb3-build-initrd` | gera kernel + initrd | sim (loop mount) |
| `nb3-gerar-squash` | gera a camada base do sistema | sim (loop mount) |

Só os dois últimos precisam de privilégio, e são passos raros (uma vez por
temporada). O resto do dia a dia roda como usuário comum.

## Documentação

- [`docs/operations.md`](docs/operations.md) — **comece aqui**: preparar a
  temporada, criar imagens, o dia da prova, solução de problemas
- [`docs/architecture.md`](docs/architecture.md) — como o sistema é feito por
  dentro e quais invariantes respeitar ao mexer
- [`docs/api.md`](docs/api.md) — referência das rotas e integração com o MOJ
- [`docs/boot-flow.md`](docs/boot-flow.md) — o caminho do boot, passo a passo
- [`docs/layer-builds.md`](docs/layer-builds.md) — pacotes extras por imagem
- [`docs/testing.md`](docs/testing.md) — como verificar que está tudo de pé

## Licença

MIT — veja [LICENSE](LICENSE).
