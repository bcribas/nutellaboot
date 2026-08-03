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

# Tamanho do arquivo remoto, para a barra saber onde é 100%. Pergunta na ÚLTIMA
# URL: o manifest traz os seeders primeiro e o servidor de arquivos por último,
# e o seeder é a máquina de um colega que pode ter desligado. Sem resposta, a
# barra vira contador (sem porcentagem nem ETA) em vez de sumir.
nb_remote_size() {
    for _rs_url in "$@"; do :; done
    wget.good --spider --server-response --timeout=10 --tries=1 \
        --ca-certificate="$NB_CA_BUNDLE" \
        --header="X-NB-Boot-Key: ${NB_BOOT_KEY:-}" "$_rs_url" 2>&1 |
        awk 'tolower($1) == "content-length:" {print $2 + 0; exit}'
}

_nb_size_of() {
    stat -c %s "$1" 2> /dev/null || echo 0
}

# Acompanha o arquivo crescendo e desenha a barra. Roda em segundo plano; quem
# chamou mata pelo PID. O tempo vem da contagem de voltas, não de `date`: uma
# dependência a menos dentro do initrd (onde já faltou `head`).
nb_progress_watch() {
    _pw_file=$1
    _pw_total=$2
    _pw_prev=0
    _pw_el=0
    while :; do
        sleep 2
        _pw_el=$((_pw_el + 2))
        _pw_now=$(_nb_size_of "$_pw_file")
        nb_ui_progress "$_pw_now" "$_pw_total" $(((_pw_now - _pw_prev) / 2)) "$_pw_el"
        _pw_prev=$_pw_now
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
    _total=0
    if [ "${NB_DL_PROGRESS:-0}" = 1 ]; then
        nb_ui_closeline
        _total=$(nb_remote_size "$@")
        [ -n "$_total" ] || _total=0
    fi

    _try=1
    _max=${NB_DOWNLOAD_TRIES:-5}
    while [ "$_try" -le "$_max" ]; do
        _watch=
        if [ "${NB_DL_PROGRESS:-0}" = 1 ]; then
            nb_progress_watch "$_dest" "$_total" &
            _watch=$!
        fi
        # --async-dns=false para honrar /etc/hosts (pin de NB_HOSTS).
        # A chave de boot vai no cabeçalho: o aria2c faz GET, e os endpoints
        # do servidor aceitam a chave tanto por POST quanto por cabeçalho.
        aria2c --quiet=true \
            --timeout=30 --connect-timeout=15 --max-tries=1 \
            --check-certificate=true --ca-certificate="$NB_CA_BUNDLE" \
            --async-dns=false --allow-overwrite=true --auto-file-renaming=false \
            --max-concurrent-downloads=1 \
            --header="X-NB-Boot-Key: ${NB_BOOT_KEY:-}" \
            -j "$_conn" -x "$_conn" -s "$_conn" \
            -d "$_dir" -o "$_base" "$@"
        _rc=$?
        if [ -n "$_watch" ]; then
            kill "$_watch" 2> /dev/null
            wait "$_watch" 2> /dev/null
            # última linha com o número final, e um \n para não deixar a barra
            # colada no que vier depois
            nb_ui_progress "$(_nb_size_of "$_dest")" "$_total" 0 0
            printf '\n'
        fi
        if [ "$_rc" -eq 0 ] && [ -s "$_dest" ]; then
            [ -n "$_watch" ] && log_begin_msg "Downloading ${NB_DL_LABEL:-$_base}"
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
