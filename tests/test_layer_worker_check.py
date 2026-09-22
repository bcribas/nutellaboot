"""O --check do worker de camadas faz um unshare de verdade e traduz o erro.

Não depende das ferramentas rootless: testa só a leitura do stderr."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKER = REPO / "tools" / "nb3-layer-worker"


def _modulo():
    import importlib.util

    spec = importlib.util.spec_from_loader("nb3_layer_worker", loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(WORKER)
    exec(compile(WORKER.read_text(encoding="utf-8"), str(WORKER), "exec"), mod.__dict__)
    return mod


def test_o_check_conhece_os_tres_motivos_de_o_namespace_falhar():
    """O --check dizia "ok" com só os binários; a construção morria depois de
    baixar a base (newuidmap ausente, código 127). O check faz um unshare de
    verdade e traduz o stderr em providência."""
    mod = _modulo()
    assert {"newuidmap", "newgidmap"} <= set(mod.FERRAMENTAS)
    casos = {
        "unshare: failed to execute newuidmap: No such file or directory": "uidmap",
        "unshare: no line matching user nutellaboot in /etc/subuid": "add-subuids",
        "unshare: write failed /proc/self/uid_map: Operation not permitted": "apparmor_restrict_unprivileged_userns",
    }
    for stderr, esperado in casos.items():
        assert esperado in mod.dica_do_unshare(stderr), stderr
    assert "§1.7" in mod.dica_do_unshare("algo inesperado")
    assert "apparmor_restrict_unprivileged_userns" in mod.dica_do_unshare(
        "unshare: cannot change root filesystem propagation: Permission denied"
    )


def test_o_sandbox_recebe_resolvedor_de_verdade_num_arquivo_comum():
    """Na imagem-mestre /etc/resolv.conf é um link para dentro de /run, que o
    bwrap monta vazio; e no host com systemd-resolved o /etc/resolv.conf é o
    stub 127.0.0.53, que não existe dentro do namespace. O apt morria com
    "Temporary failure resolving" depois de tudo o mais ter dado certo."""
    mod = _modulo()
    sh = mod.MOUNT_SH
    assert 'rm -f "$WORK/merged/etc/resolv.conf"' in sh, "o link para /run tem de sair antes de escrever"
    assert "/run/systemd/resolve/resolv.conf" in sh, "os servidores de verdade, não o stub"
    assert "127\\." in sh and "1.1.1.1" in sh, "só loopback cai num resolvedor público"
    assert sh.index("resolv.conf") < sh.index("bwrap --bind"), "antes de entrar no sandbox"
