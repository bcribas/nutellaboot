# data/ — banco-filesystem do NutellaBoot 3

Este diretório é o estado vivo do servidor (imagens, chaves, telemetria, filas).
Nada aqui é versionado — veja `docs/architecture.md` para o esquema completo.

Estrutura criada pelo `tools/nb3-init` (produção), pelo `tools/nb3-seed-testdata`
(teste) ou pela própria API:

```
server.json                     configuração global do servidor
sessions.json                   sessões do console (0600, 30 dias)
invites.json                    convites de sub-admin (o código é a credencial)
keys/admin.json                 hashes das chaves de administração
keys/services.json              hashes das chaves de serviço (MOJ) com escopos
models/<nome>/                  modelo: camadas + formulário (schema.json)
site-images/<id>/               a imagem de uma sala: token, chaves, config
owners/<slug>.json              identidade de quem entrou por convite
layerbuilds/{queue,running,done,failed}/   fila do builder de camadas
blobs/                          squashfs construídos localmente (servidos em /blobs/)
usb/                            imagens de pendrive (genérica e por sala)
publish/<arquivo>.json           estado do envio ao servidor de arquivos
```

Os nomes antigos eram `templates/` e `images/`; a migração está em
`tools/nb3-migrate-names`.
