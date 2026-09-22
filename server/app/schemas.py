"""Os formatos das respostas, para o OpenAPI (documentação pura).

O OpenAPI publicado dizia `additionalProperties: true` em quase toda resposta:
quem integrava precisava ler `routers/` e `services/` para saber o formato de
uma máquina ou de um ponto de sample. Estes modelos descrevem o que as rotas
JÁ devolvem.

Eles NÃO são `response_model`. Ligar um modelo de verdade numa rota faz o
FastAPI validar e REESCREVER a resposta por ele: coage tipos (`boots: 2.0` vira
`2`), reordena chaves e, sem `extra="allow"`, engole campo que o modelo não
conhece. O status da máquina é JSON livre de propósito (um coletor novo em
`parts.d/` entra sem mexer no servidor), então aqui o esquema é só injetado no
documento (`aplicar`), e o fio continua sendo exatamente o dict do serviço.

Todo modelo é aberto (`extra="allow"` → `additionalProperties: true`) e todo
campo é opcional: a frota é mista, e campo novo nosso não pode quebrar o
validador de um cliente. `tests/test_openapi_shapes.py` valida respostas reais
contra estes modelos e exige os campos do contrato congelado com o MOJ.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import models_json_schema


class Aberto(BaseModel):
    model_config = ConfigDict(extra="allow")


class ErrorBody(Aberto):
    detail: Any = Field(None, description="Frase em português (lista, no 422). Não decida por ela.")
    code: str | None = Field(None, description="Código estável; catálogo em GET /api/v1/events/types")


# --- máquina ---


class HwInfo(Aberto):
    processor: str | None = None
    cores: int | None = None
    memtotal_mb: int | None = None
    machine_id: str | None = Field(None, description="md5 do MAC estável, 32 hex")
    boot_id: str | None = None
    mac: str | None = Field(None, description="aa-bb-cc-dd-ee-ff, minúsculo com hífen")
    hostname: str | None = None
    dmi_uuid: str | None = None
    product_vendor: str | None = None
    product_name: str | None = None
    uptime_s: int | None = None
    last_boot: int | None = None
    monitors: int | None = Field(None, description="monitores acesos (conectados e com saída ativa)")
    monitor_outputs: list[str] | None = Field(None, description="os conectores deles: DP-1, HDMI-A-1…")


class Operations(Aberto):
    firewall: bool | None = None
    screen_lock: bool | None = None
    editors_time: dict[str, Any] | None = Field(None, description="minutos acumulados por editor")
    editors_time_since: int | None = Field(None, description="desde quando `editors_time` conta")


class SysDisk(Aberto):
    home_pct: float | None = None
    home_free_mb: float | None = None


class MachineStatus(Aberto):
    """A telemetria, como o agente a mandou. JSON livre: só os campos de uso
    comum estão descritos."""

    t_agent: int | None = Field(None, description="relógio da máquina no envio")
    agent_version: str | None = Field(None, description="ausente = agente antigo")
    capabilities: list[str] | None = None
    hwinfo: HwInfo | None = None
    sysresources: dict[str, Any] | None = Field(
        None, description="mem_pct, loadavg, swap, psi_mem/psi_cpu/psi_io, oom_kills, idle_s…"
    )
    sysdisk: SysDisk | None = None
    operations: Operations | None = None


class Alert(Aberto):
    id: str | None = None
    kind: str | None = Field(None, description="usb.storage, usb.phone, …, display.multiple, identity.duplicate")
    detail: str | None = None
    vendor: str | None = None
    other_mac: str | None = Field(None, description="só em identity.duplicate")
    at: float | None = None


class Binding(Aberto):
    user_id: str | None = None
    name: str | None = Field(None, description="só no vínculo de nome livre (sem user_id)")
    seat: str | None = None
    source: str | None = None
    by: str | None = None
    bound_at: int | None = None
    client_at: int | None = Field(None, description="o `at` que o cliente mandou")
    boot_id: str | None = None
    note: str | None = None
    roster_entry_created: bool | None = None


class Lock(Aberto):
    locked: bool | None = None
    since: float | None = None
    by: str | None = None


class Machine(Aberto):
    mac: str | None = None
    first_seen: float | None = None
    last_seen: float | None = None
    seconds_since_contact: float | None = None
    online: bool | None = Field(None, description="contato nos últimos 90 s")
    last_boot: float | None = None
    boots: int | None = None
    boot_id: str | None = None
    boot_seen_at: float | None = None
    editors_reset_at: float | None = None
    pending: int | None = Field(None, description="ordens na fila")
    binding: Binding | None = None
    lock: Lock | None = None
    alerts: list[Alert] | None = None
    status: MachineStatus | None = None


class MachineList(Aberto):
    machines: list[Machine] | None = None
    rejected: list[dict[str, Any]] | None = Field(
        None, description="só com a lista vazia e sem `active_since`: quem tentou reportar com identificação inválida"
    )


# --- samples ---


class SamplePoint(Aberto):
    t: int | None = None
    mem: float | None = Field(None, description="% de memória usada")
    ld: float | None = Field(None, description="load1")
    sw: float | None = Field(None, description="swap em MB")
    hd: float | None = Field(None, description="% do /home")
    ed: list[str] | None = Field(None, description="editores abertos")
    fw: bool | None = None
    lk: bool | None = None
    psi_mem: float | None = None
    psi_cpu: float | None = None
    psi_io: float | None = None
    oom: int | None = Field(None, description="ACUMULADO: some os incrementos positivos na janela")
    idle: int | None = None
    skew: int | None = Field(None, description="relógio do servidor menos o da máquina, em s")
    edm: float | None = None
    eds: int | None = None


class SamplesWindow(Aberto):
    """Também é o formato de cada linha do lote NDJSON."""

    mac: str | None = None
    points: list[SamplePoint] | None = None
    native_points: int | None = None
    resampled: bool | None = None
    interval_s: int | None = None
    since: int | None = None
    until: int | None = None
    truncated: bool | None = Field(None, description="o teto do arquivo cortou dado dentro da janela")


# --- roster e vínculos ---


class RosterEntry(Aberto):
    user_id: str | None = None
    name: str | None = None
    display_name: str | None = None
    organization: dict[str, Any] | None = Field(None, description="{id, name}")
    country: str | None = Field(None, description="rótulo; alpha-2 recomendado")
    seat: str | None = None
    source: Literal["binding"] | None = Field(None, description="entrada criada a reboque de um vínculo")


class Roster(Aberto):
    roster: list[RosterEntry] | None = None
    logos: list[str] | None = None


class RosterUpsert(Aberto):
    ok: bool | None = None
    created: bool | None = None
    entry: RosterEntry | None = None


class RosterReplaced(Aberto):
    ok: bool | None = None
    entries: int | None = None
    kept_bound: list[str] | None = None


class BindingWithMac(Binding):
    mac: str | None = None


class BindingList(Aberto):
    bindings: list[BindingWithMac] | None = None


class BindingHistoryLine(Aberto):
    event: Literal["bound", "unbound"] | None = None
    mac: str | None = None
    at: int | None = Field(None, description="só no unbound; o bound traz bound_at")
    bound_at: int | None = None
    by: str | None = None
    source: str | None = None
    user_id: str | None = None


class BindingHistory(Aberto):
    history: list[BindingHistoryLine] | None = None


class BatchBindingResult(Aberto):
    mac: str | None = None
    ok: bool | None = None
    binding: Binding | None = None
    code: str | None = None
    detail: Any = None


class BatchBindings(Aberto):
    results: list[BatchBindingResult] | None = None
    bound: int | None = None
    failed: int | None = None


# --- comandos ---


class CommandResult(Aberto):
    command_id: str | None = None
    machines: int | None = None


class CommandsAllowed(Aberto):
    allowed: list[str] | None = None
    blocked: dict[str, str] | None = None


class CommandTarget(Aberto):
    mac: str | None = None
    state: Literal["acked", "pending", "expired"] | None = None
    status: str | None = None
    at: int | None = None
    output_bytes: int | None = None


class CommandStatus(Aberto):
    command_id: str | None = None
    command: str | None = None
    args: str | None = None
    by: str | None = None
    created_at: int | None = None
    not_before: int | None = None
    expires_at: int | None = None
    machines: int | None = None
    summary: dict[str, int] | None = None
    targets: list[CommandTarget] | None = None


# --- webhooks ---


class WebhookEntry(Aberto):
    id: str | None = None
    url: str | None = None
    secret: str | None = Field(None, description='sempre mascarado: "***" ou ""')
    events: list[str] | None = Field(None, description="[] = todos")
    owner: str | None = Field(None, description="admin ou service:<nome>")
    created_at: int | None = None
    created: bool | None = None


class WebhookList(Aberto):
    webhooks: list[WebhookEntry] | None = None


class WebhookPayload(Aberto):
    """O corpo que o NutellaBoot ENVIA (assinado em X-NB-Signature)."""

    event: str | None = None
    image: str | None = None
    at: int | None = Field(None, description="instante do EVENTO; igual nas tentativas")
    delivery: str | None = Field(None, description="id da entrega; deduplique por ele")
    data: dict[str, Any] | None = None


# --- quem sou eu, e as imagens ---


class Whoami(Aberto):
    kind: Literal["admin", "subadmin", "service"] | None = None
    label: str | None = None
    name: str | None = Field(None, description="chave de serviço")
    scopes: list[str] | None = Field(None, description="chave de serviço")
    image_globs: list[str] | None = Field(None, description="chave de serviço; [] = todas")
    images: list[str] | None = Field(None, description="chave de serviço: os ids que os globs cobrem agora")
    owner: str | None = Field(None, description="console")
    quotas: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None


class SiteImage(Aberto):
    id: str | None = None
    fullname: str | None = None
    country: str | None = None
    machines_total: int | None = Field(None, description="só para chave de serviço")
    model: str | None = None
    namespace: str | None = None
    unlocked: bool | None = None
    created_at: float | None = None
    owner: str | None = Field(None, description="só para o console dono")
    owner_kind: str | None = None
    owner_label: str | None = None
    owner_ref: str | None = None


class SiteImageList(Aberto):
    images: list[SiteImage] | None = None


_I = "/api/v1/site-images/{image}"
DOCS: dict[tuple[str, str], type[BaseModel]] = {
    ("get", "/api/v1/whoami"): Whoami,
    ("get", "/api/v1/site-images"): SiteImageList,
    ("get", _I): SiteImage,
    ("get", f"{_I}/machines"): MachineList,
    ("get", f"{_I}/machines/{{mac}}"): Machine,
    ("get", f"{_I}/machines/{{mac}}/samples"): SamplesWindow,
    ("get", f"{_I}/roster"): Roster,
    ("put", f"{_I}/roster"): RosterReplaced,
    ("post", f"{_I}/roster"): RosterUpsert,
    ("put", f"{_I}/machines/{{mac}}/binding"): Binding,
    ("get", f"{_I}/machines/{{mac}}/binding/history"): BindingHistory,
    ("get", f"{_I}/bindings"): BindingList,
    ("put", f"{_I}/bindings"): BatchBindings,
    ("get", f"{_I}/commands"): CommandsAllowed,
    ("post", f"{_I}/commands"): CommandResult,
    ("get", f"{_I}/commands/{{command_id}}"): CommandStatus,
    ("get", f"{_I}/webhooks"): WebhookList,
    ("post", f"{_I}/webhooks"): WebhookEntry,
    ("put", f"{_I}/webhooks/{{webhook_id}}"): WebhookEntry,
}
NDJSON = {("get", f"{_I}/samples"): SamplesWindow}


def aplicar(doc: dict) -> dict:
    """Põe os esquemas no documento OpenAPI já gerado. Não toca em rota alguma."""
    modelos = sorted({*DOCS.values(), *NDJSON.values(), ErrorBody, WebhookPayload}, key=lambda m: m.__name__)
    _, defs = models_json_schema(
        [(m, "serialization") for m in modelos], ref_template="#/components/schemas/{model}"
    )
    doc.setdefault("components", {}).setdefault("schemas", {}).update(defs.get("$defs", {}))

    def ref(modelo) -> dict:
        return {"$ref": f"#/components/schemas/{modelo.__name__}"}

    for (metodo, caminho), modelo in DOCS.items():
        respostas = doc["paths"][caminho][metodo]["responses"]
        for status in ("200", "201"):
            if status in respostas:
                respostas[status].setdefault("content", {})["application/json"] = {"schema": ref(modelo)}
    for (metodo, caminho), modelo in NDJSON.items():
        ok = doc["paths"][caminho][metodo]["responses"]["200"]
        ok["description"] = "NDJSON: uma linha por máquina, cada uma neste formato"
        ok["content"] = {"application/x-ndjson": {"schema": ref(modelo)}}
    for caminho, ops in doc["paths"].items():
        if not caminho.startswith("/api/v1"):
            continue
        for op in ops.values():
            if isinstance(op, dict) and "responses" in op:
                op["responses"].setdefault(
                    "4XX",
                    {"description": "Erro: decida por `code`", "content": {"application/json": {"schema": ref(ErrorBody)}}},
                )
    doc["webhooks"] = {
        "nb3-event": {
            "post": {
                "summary": "Evento enviado ao webhook configurado na imagem",
                "description": "Cabeçalhos: X-NB-Signature (sha256=HMAC do corpo cru), X-NB-Delivery, "
                "X-NB-Attempt, X-NB-Event, X-NB-Webhook-Id.",
                "requestBody": {"content": {"application/json": {"schema": ref(WebhookPayload)}}},
                "responses": {"2XX": {"description": "recebido; qualquer outro status é tentado de novo (3 vezes)"}},
            }
        }
    }
    return doc
