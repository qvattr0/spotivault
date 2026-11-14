/*
 * Makes the Spotify client see $DEVICE_NAME as the machine's hostname.
 *
 * The client names its Spotify Connect device after gethostname(). A container's real hostname
 * is a Docker option (`hostname:`), which the UGOS Pro Docker app may not expose, while
 * environment variables are always editable there. Loaded into the Spotify process only, with
 * LD_PRELOAD. When DEVICE_NAME is empty, the real hostname is used.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <sys/utsname.h>
#include <unistd.h>

static const char *device_name(void) {
    const char *n = getenv("DEVICE_NAME");
    return (n && *n) ? n : NULL;
}

int gethostname(char *buf, size_t len) {
    const char *n = device_name();
    if (!n) {
        int (*real)(char *, size_t) = (int (*)(char *, size_t))dlsym(RTLD_NEXT, "gethostname");
        return real(buf, len);
    }
    size_t l = strlen(n);
    if (l + 1 > len) {
        errno = ENAMETOOLONG;
        return -1;
    }
    memcpy(buf, n, l + 1);
    return 0;
}

int uname(struct utsname *u) {
    int (*real)(struct utsname *) = (int (*)(struct utsname *))dlsym(RTLD_NEXT, "uname");
    int r = real(u);
    const char *n = device_name();
    if (r == 0 && n) {
        strncpy(u->nodename, n, sizeof(u->nodename) - 1);
        u->nodename[sizeof(u->nodename) - 1] = '\0';
    }
    return r;
}
