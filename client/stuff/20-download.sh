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

# nb_download <dest> <conexoes> <url> [url...]
nb_download() {
    _dest=$1
    _conn=$2
    shift 2
    [ -z "$1" ] && return 1

    _dir=$(dirname "$_dest")
    _base=$(basename "$_dest")
    mkdir -p "$_dir"
    rm -f "$_dest"

    log_begin_msg "Downloading $_base"
    _try=1
    _max=${NB_DOWNLOAD_TRIES:-5}
    while [ "$_try" -le "$_max" ]; do
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

    while read -r MD5 FILE URLS; do
        [ -z "$FILE" ] && continue
        if [ -e "$_storage/$FILE" ]; then
            if nutella_md5sum "$MD5" "$_storage/$FILE"; then
                nb_warn "using the cached copy of $FILE"
                continue
            fi
            rm -f "$_storage/$FILE"
        fi
        # shellcheck disable=SC2086
        if ! nb_download "$_storage/$FILE" 10 $URLS; then
            nb_warn "could not download $FILE"
            return 1
        fi
        if ! nutella_md5sum "$MD5" "$_storage/$FILE"; then
            rm -f "$_storage/$FILE"
            return 1
        fi
    done < "$_fstab"
}
