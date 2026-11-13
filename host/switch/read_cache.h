/* Switch-only read-ahead for immutable extract files. Not used for saves. */
#ifndef EIDOS_SWITCH_READ_CACHE_H
#define EIDOS_SWITCH_READ_CACHE_H
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define SWITCH_READ_BLOCK (64u * 1024u)
#define SWITCH_READ_CACHES 64u /* at most 4 MiB outside the module heap */

typedef struct SwitchReadCache {
    unsigned char *bytes;
    off_t start;
    size_t length;
} SwitchReadCache;

static unsigned switch_read_cache_count;

static void switch_read_cache_free(SwitchReadCache *cache)
{
    if (cache->bytes != NULL) {
        free(cache->bytes);
        switch_read_cache_count--;
    }
    memset(cache, 0, sizeof(*cache));
}

static ssize_t switch_read_cached(int fd, void *out, size_t length,
                                  SwitchReadCache *cache)
{
    off_t pos;
    size_t take;
    ssize_t got;

    if (length == 0 || length >= SWITCH_READ_BLOCK) {
        return read(fd, out, length);
    }
    if (cache->bytes == NULL) {
        if (switch_read_cache_count >= SWITCH_READ_CACHES) {
            return read(fd, out, length);
        }
        cache->bytes = (unsigned char *)malloc(SWITCH_READ_BLOCK);
        if (cache->bytes == NULL) {
            return read(fd, out, length);
        }
        switch_read_cache_count++;
    }
    pos = lseek(fd, 0, SEEK_CUR);
    if (pos < 0) {
        return -1;
    }
    if (pos < cache->start || (size_t)(pos - cache->start) >= cache->length) {
        got = read(fd, cache->bytes, SWITCH_READ_BLOCK);
        if (got <= 0) {
            return got;
        }
        cache->start = pos;
        cache->length = (size_t)got;
    }
    take = cache->length - (size_t)(pos - cache->start);
    if (take > length) {
        take = length;
    }
    /* Keep the native descriptor position exact: fd_seek, fd_tell and the
     * existing pread save/restore code continue to work without special cases. */
    if (lseek(fd, pos + (off_t)take, SEEK_SET) < 0) {
        return -1;
    }
    memcpy(out, cache->bytes + (size_t)(pos - cache->start), take);
    return (ssize_t)take;
}
#endif
