#!/usr/bin/env python3
"""Switch GPU staging and SD read-ahead regression checks."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gl_imports", ROOT / "tools/wasm_gl_imports.py")
imports = importlib.util.module_from_spec(spec)
spec.loader.exec_module(imports)

MAP_HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define APIENTRY
typedef uint32_t u32;
typedef int GLint;
typedef unsigned GLenum;
typedef unsigned GLbitfield;
typedef unsigned char GLboolean;
typedef intptr_t GLintptr;
typedef intptr_t GLsizeiptr;
struct w2c_env { int unused; };
static int host_gl_es, size = 256, allocations, frees, unmaps, fail_alloc;
static unsigned char memory[8192], gpu[512];
static u32 next = 16;
static void *host_ptr(u32 addr, u32 length) {
    assert(addr + length <= sizeof memory);
    return memory + addr;
}
static u32 host_malloc(u32 length) {
    u32 addr = next;
    if (fail_alloc) return 0;
    allocations++;
    next += length;
    assert(next <= sizeof memory);
    return addr;
}
static void host_free(u32 addr) { assert(addr != 0); frees++; }
static void parameter(GLenum target, GLenum pname, GLint *out) {
    (void)target; (void)pname; *out = size;
}
static void *map(GLenum target, GLenum access) { (void)target; (void)access; return gpu; }
static GLboolean unmap(GLenum target) { (void)target; unmaps++; return 1; }
static void *gl_proc(const char *name) {
    if (!strcmp(name, "glGetBufferParameteriv")) return (void *)parameter;
    if (!strcmp(name, "glMapBuffer")) return (void *)map;
    if (!strcmp(name, "glUnmapBuffer")) return (void *)unmap;
    abort();
}
'''
MAP_MAIN = r'''
int main(void) {
    u32 first, addr;
    int i;
    memset(gpu, 0x5a, sizeof gpu);
    first = w2c_env_glMapBuffer(NULL, 0x88EB, 0x88B8);
    assert(first && !memcmp(memory + first, gpu, 256));
    w2c_env_glUnmapBuffer(NULL, 0x88EB);
    for (i = 0; i < 1000; i++) {
        addr = w2c_env_glMapBuffer(NULL, 0x88EB, 0x88B8);
        assert(addr == first);
        w2c_env_glUnmapBuffer(NULL, 0x88EB);
    }
    assert(allocations == 1 && frees == 0 && unmaps == 1001);
    size = 512;
    addr = w2c_env_glMapBuffer(NULL, 0x88EB, 0x88B9);
    assert(addr && allocations == 2 && frees == 1);
    memset(memory + addr, 0x32, 512);
    w2c_env_glUnmapBuffer(NULL, 0x88EB);
    assert(!memcmp(memory + addr, gpu, 512));
    /* All four active mappings are accounted for; a fifth is unmapped. */
    for (i = 0; i < 4; i++) assert(w2c_env_glMapBuffer(NULL, (u32)i + 1, 0x88B8));
    i = unmaps;
    assert(w2c_env_glMapBuffer(NULL, 8, 0x88B8) == 0 && unmaps == i + 1);
    for (i = 0; i < 4; i++) w2c_env_glUnmapBuffer(NULL, (u32)i + 1);
    size = 1024;
    fail_alloc = 1;
    i = unmaps;
    assert(w2c_env_glMapBuffer(NULL, 1, 0x88B8) == 0 && unmaps == i + 1);
    return 0;
}
'''
IO_HARNESS = r'''
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>
static int reads;
static ssize_t counted_read(int fd, void *out, size_t n) {
    reads++;
    return read(fd, out, n);
}
#define read counted_read
#include "host/switch/read_cache.h"
#undef read
int main(int argc, char **argv) {
    SwitchReadCache cache = {0};
    unsigned char data[150000], out[70000];
    int fd, i, before;
    ssize_t got;
    off_t save;
    (void)argc;
    for (i = 0; i < (int)sizeof data; i++) data[i] = (unsigned char)(i * 13 + i / 256);
    fd = open(argv[1], O_RDWR | O_CREAT | O_TRUNC, 0600);
    assert(fd >= 0 && write(fd, data, sizeof data) == sizeof data);
    assert(lseek(fd, 0, SEEK_SET) == 0);
    for (i = 0; i < 100; i++) {
        assert(switch_read_cached(fd, out, 32, &cache) == 32);
        assert(!memcmp(out, data + i * 32, 32));
    }
    assert(reads == 1); /* 100 small requests became one storage read */
    assert(lseek(fd, 25, SEEK_SET) == 25);
    assert(switch_read_cached(fd, out, 100, &cache) == 100);
    assert(!memcmp(out, data + 25, 100) && reads == 1);
    save = lseek(fd, 0, SEEK_CUR);
    assert(lseek(fd, 90000, SEEK_SET) == 90000);
    assert(switch_read_cached(fd, out, 1024, &cache) == 1024);
    assert(!memcmp(out, data + 90000, 1024));
    assert(lseek(fd, save, SEEK_SET) == save); /* pread's existing restore */
    assert(switch_read_cached(fd, out, 32, &cache) == 32);
    assert(!memcmp(out, data + save, 32));
    assert(lseek(fd, sizeof data - 10, SEEK_SET) == sizeof data - 10);
    got = switch_read_cached(fd, out, 32, &cache);
    assert(got == 10 && !memcmp(out, data + sizeof data - 10, 10));
    assert(switch_read_cached(fd, out, 32, &cache) == 0);
    assert(lseek(fd, 0, SEEK_SET) == 0);
    before = reads;
    assert(switch_read_cached(fd, out, sizeof out, &cache) == sizeof out);
    assert(reads == before + 1 && !memcmp(out, data, sizeof out));
    switch_read_cache_free(&cache);
    assert(switch_read_cache_count == 0 && cache.bytes == NULL);
    close(fd);
    return 0;
}
'''


class SwitchRuntime(unittest.TestCase):
    def test_staging_and_read_ahead(self):
        cc = shutil.which(os.environ.get("CC", "gcc"))
        self.assertIsNotNone(cc, "a C compiler is required")
        mapping = "static struct {" + imports.HEAD.split(
            "/* A mapped buffer:", 1)[1].split("static struct {", 1)[1]
        with tempfile.TemporaryDirectory() as tmp:
            for name, source in (("map", MAP_HARNESS + mapping + MAP_MAIN),
                                 ("io", IO_HARNESS)):
                with self.subTest(component=name):
                    path = Path(tmp) / (name + ".c")
                    binary = Path(tmp) / (name + (".exe" if os.name == "nt" else ""))
                    path.write_text(source, encoding="utf-8")
                    subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                                    "-D__SWITCH__", "-I", str(ROOT), str(path),
                                    "-o", str(binary)], check=True)
                    subprocess.run([str(binary), str(Path(tmp) / "data.bin")], check=True)


if __name__ == "__main__":
    unittest.main()
