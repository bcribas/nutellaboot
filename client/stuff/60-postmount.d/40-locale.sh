# shellcheck shell=sh
nb3_post_locale() {
    _lang=${SYSTEM_LOCALE:-en_US.UTF-8}
    {
        echo "LANG=$_lang"
        for _v in CTYPE NUMERIC TIME COLLATE MONETARY MESSAGES PAPER NAME \
            ADDRESS TELEPHONE MEASUREMENT IDENTIFICATION ALL; do
            echo "LC_$_v=\"$_lang\""
        done
    } > "${rootmnt?}/etc/default/locale"
}
