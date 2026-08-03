# shellcheck shell=sh
# Downloads com TLS verificado de verdade e retry que funciona.
#
# Diferenças críticas em relação ao nb2:
#  - certificado SEMPRE verificado (o nb2 usava --check-certificate=false em
#    todo download; era impossível saber se o arquivo vinha de fonte confiável);
#  - retry em QUALQUER código de saída (o nb2 só repetia com exit==1, então a
#    maioria das falhas reais do aria2 passava direto);
#  - retorno reflete o resultado real (o nb2 devolvia sucesso/falha pelo
#    contador de tentativas);
#  - aceita VÁRIAS URLs do mesmo arquivo: o aria2 usa todas como espelhos e
#    contorna seeder morto sozinho.

# A barra vem dos números do PRÓPRIO aria2.
#
# Medir o arquivo não funciona: o aria2 pré-aloca, então ele nasce com o
# tamanho final e a barra marcava 100% desde o primeiro segundo. E perguntar o
# tamanho antes, com um HEAD, trazia o Content-Length do REDIRECIONAMENTO
# quando a URL redireciona — daí saía "4 kB of 178 B".
#
# O aria2 imprime, uma vez por segundo, uma linha como
#   [#fbbee4 2.0MiB/300MiB(0%) CN:1 DL:1.0MiB ETA:4m56s]
# e continua imprimindo quando a saída é um cano (conferido). É dela que saem
# baixado, total, velocidade e tempo restante.
#
# Num TERMINAL o aria2 separa as atualizações com \r (para reescrever no
# lugar); num CANO, com \n. Aqui a saída é sempre um cano, então o separador é
# a quebra de linha — mas o corte pelo último \r fica como rede, porque com
# RS='\r' e uma entrada sem nenhum CR o awk lê tudo como UM registro e a barra
# imprime uma vez só, no começo, e congela.
nb_aria_progress() {
    awk '
        function bytes(s,   n, u) {
            n = s + 0
            u = s
            sub(/^[0-9.]+/, "", u)
            if (u ~ /^GiB/) return n * 1073741824
            if (u ~ /^MiB/) return n * 1048576
            if (u ~ /^KiB/) return n * 1024
            return n
        }
        function segundos(s,   t, n) {
            t = 0
            while (match(s, /[0-9]+[dhms]/)) {
                n = substr(s, RSTART, RLENGTH - 1) + 0
                u = substr(s, RSTART + RLENGTH - 1, 1)
                if (u == "d") t += n * 86400
                else if (u == "h") t += n * 3600
                else if (u == "m") t += n * 60
                else t += n
                s = substr(s, RSTART + RLENGTH)
            }
            return t
        }
        /\[#[0-9a-f]+ / {
            sub(/^.*\r/, "")
            feito = total = vel = eta = 0
            if (match($0, /[0-9.]+[KMGT]?i?B\/[0-9.]+[KMGT]?i?B/)) {
                par = substr($0, RSTART, RLENGTH)
                split(par, ab, "/")
                feito = bytes(ab[1]); total = bytes(ab[2])
            }
            if (match($0, /DL:[0-9.]+[KMGT]?i?B/)) vel = bytes(substr($0, RSTART + 3, RLENGTH - 3))
            if (match($0, /ETA:[0-9dhms]+/)) eta = segundos(substr($0, RSTART + 4, RLENGTH - 4))
            # %d e não print: com print o awk sai em notação científica
            # (5.03316e+06) e a aritmética do shell recusa
            printf "%d %d %d %d\n", feito, total, vel, eta
            fflush()
        }
    ' | while read -r _ap_feito _ap_total _ap_vel _ap_eta; do
        nb_ui_progress "$_ap_feito" "$_ap_total" "$_ap_vel" "$_ap_eta"
    done
}

# nb_download <dest> <conexoes> <url> [url...]
#
# Com NB_DL_PROGRESS=1 mostra a barra: é para as camadas, que têm GB. O mesmo
# nb_download baixa o wallpaper e a chave do CLion, onde uma barra seria ruído.
nb_download() {
    _dest=$1
    _conn=$2
    shift 2
    [ -z "$1" ] && return 1

    _dir=$(dirname "$_dest")
    _base=$(basename "$_dest")
    mkdir -p "$_dir"
    rm -f "$_dest"

    log_begin_msg "Downloading ${NB_DL_LABEL:-$_base}"
    _rcfile=$_dir/.nb3-dlrc

    _try=1
    _max=${NB_DOWNLOAD_TRIES:-5}
    while [ "$_try" -le "$_max" ]; do
        # --async-dns=false para honrar /etc/hosts (pin de NB_HOSTS).
        # A chave de boot vai no cabeçalho: o aria2c faz GET, e os endpoints
        # do servidor aceitam a chave tanto por POST quanto por cabeçalho.
        if [ "${NB_DL_PROGRESS:-0}" = 1 ]; then
            nb_ui_closeline
            # o código de saída vai para um arquivo: num cano, `$?` é do último
            # comando (o awk), e é o do aria2 que decide se vale repetir
            rm -f "$_rcfile"
            {
                # stdbuf -o0: sem ele os números ficam no buffer do libc e a
                # barra só se mexe quando o download acaba
                stdbuf -o0 aria2c --quiet=false --console-log-level=warn \
                    --show-console-readout=true --summary-interval=0 \
                    --timeout=30 --connect-timeout=15 --max-tries=1 \
                    --check-certificate=true --ca-certificate="$NB_CA_BUNDLE" \
                    --async-dns=false --allow-overwrite=true --auto-file-renaming=false \
                    --max-concurrent-downloads=1 \
                    --header="X-NB-Boot-Key: ${NB_BOOT_KEY:-}" \
                    -j "$_conn" -x "$_conn" -s "$_conn" \
                    -d "$_dir" -o "$_base" "$@" 2>&1
                echo $? > "$_rcfile"
            } | nb_aria_progress
            _rc=$(cat "$_rcfile" 2> /dev/null || echo 1)
            rm -f "$_rcfile"
            printf '\n'
            log_begin_msg "Downloading ${NB_DL_LABEL:-$_base}"
        else
            aria2c --quiet=true \
                --timeout=30 --connect-timeout=15 --max-tries=1 \
                --check-certificate=true --ca-certificate="$NB_CA_BUNDLE" \
                --async-dns=false --allow-overwrite=true --auto-file-renaming=false \
                --max-concurrent-downloads=1 \
                --header="X-NB-Boot-Key: ${NB_BOOT_KEY:-}" \
                -j "$_conn" -x "$_conn" -s "$_conn" \
                -d "$_dir" -o "$_base" "$@"
            _rc=$?
        fi
        if [ "$_rc" -eq 0 ] && [ -s "$_dest" ]; then
            log_end_msg
            return 0
        fi
        log_failure_msg "attempt $_try/$_max failed ($_rc) for $_base"
        rm -f "$_dest"
        [ "$_try" -lt "$_max" ] && sleep $((_try * 5))
        _try=$((_try + 1))
    done
    return 1
}

# nb_get <url> — imprime o corpo no stdout (para respostas curtas da API),
# autenticando com a chave de boot por POST.
nb_get() {
    wget.good -q -O - --timeout=20 --tries=2 \
        --ca-certificate="$NB_CA_BUNDLE" \
        --post-data="key=${NB_BOOT_KEY:-}" "$1"
}

nutella_md5sum() {
    _want=$1
    _file=$2
    log_begin_msg "Checking MD5 of $(basename "$_file")"
    _got=$(md5sum "$_file" | awk '{print $1}')
    if [ "$_got" = "$_want" ]; then
        log_end_msg
        return 0
    fi
    log_failure_msg "MD5 mismatch: expected $_want, got $_got"
    return 1
}

# Baixa o manifest e cada camada, reaproveitando cache válido por md5.
# Manifest: linhas "MD5 ARQUIVO URL1 URL2 ..." (extras primeiro).
download_boot_files() {
    _storage=$1
    _fstab=$_storage/fstab.nutella

    if ! nb_get "$NB_SERVER/boot/v3/$IMAGEROOT/manifest" > "$_fstab" || [ ! -s "$_fstab" ]; then
        nb_warn "could not download the layer manifest"
        return 1
    fi
    printf "  ----- layers -----\n"
    cat "$_fstab"
    printf "  ------------------\n"

    _nlayers=0
    while read -r _ _f _; do
        [ -n "$_f" ] && _nlayers=$((_nlayers + 1))
    done < "$_fstab"
    _layer=0

    while read -r MD5 FILE URLS; do
        [ -z "$FILE" ] && continue
        _layer=$((_layer + 1))
        if [ -e "$_storage/$FILE" ]; then
            if nutella_md5sum "$MD5" "$_storage/$FILE"; then
                nb_warn "using the cached copy of $FILE"
                continue
            fi
            rm -f "$_storage/$FILE"
        fi
        # a camada base tem GB: sem barra, a tela fica parada em "Downloading"
        # por vários minutos e quem está com a sala esperando não sabe se travou
        NB_DL_PROGRESS=1
        NB_DL_LABEL="layer $_layer/$_nlayers: $FILE"
        export NB_DL_PROGRESS NB_DL_LABEL
        # shellcheck disable=SC2086
        if ! nb_download "$_storage/$FILE" 10 $URLS; then
            NB_DL_PROGRESS=0 NB_DL_LABEL=
            nb_warn "could not download $FILE"
            return 1
        fi
        NB_DL_PROGRESS=0
        NB_DL_LABEL=
        if ! nutella_md5sum "$MD5" "$_storage/$FILE"; then
            rm -f "$_storage/$FILE"
            return 1
        fi
    done < "$_fstab"
}
