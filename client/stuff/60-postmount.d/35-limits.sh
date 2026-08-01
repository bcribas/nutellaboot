# shellcheck shell=sh
nb3_post_limits() {
    echo 'icpc  hard  nproc 50000' > "${rootmnt?}/etc/security/limits.conf"
    echo '*  hard  nproc 50000' >> "${rootmnt?}/etc/security/limits.conf"
    echo 'kernel.dmesg_restrict = 0' > "${rootmnt?}/etc/sysctl.d/10-local.conf"
}
