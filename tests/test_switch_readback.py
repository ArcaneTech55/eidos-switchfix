#!/usr/bin/env python3
"""Exercise the generated Switch GL readback wrapper with a mock driver."""
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
wrapper = imports.HEAD.split("void w2c_env_glReadPixels(", 1)[1].split(
    "void w2c_env_glShaderSource(", 1)[0]
wrapper = "void w2c_env_glReadPixels(" + wrapper

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define APIENTRY
typedef uint32_t u32;
typedef int GLint;
typedef int GLsizei;
typedef unsigned GLenum;
struct w2c_env { int unused; };
static int host_gl_es, pack, calls, expect_rows, rgb;
static unsigned char mem[4096];
static void *gl_ptr(u32 p) { return p ? mem + p : NULL; }
static void get_int(GLenum name, GLint *v) {
    *v = name == 0x88ED ? pack : 4;
}
static void read_pixels(GLint x, GLint y, GLsizei w, GLsizei h,
                        GLenum fmt, GLenum type, void *out) {
    size_t row = rgb ? 12 : 16;
    assert(x == 2 && w == 4 && type == 0x1401);
    assert(y == 5 + (expect_rows ? calls : 0));
    assert(h == (expect_rows ? 1 : 3));
    assert(fmt == (rgb ? 0x1907u : 0x1908u));
    assert(out == (pack ? (void *)(uintptr_t)(64 + calls * row) : mem + 64 + calls * row));
    calls++;
}
static void *gl_proc(const char *s) {
    if (!strcmp(s, "glReadPixels")) return (void *)read_pixels;
    assert(!strcmp(s, "glGetIntegerv"));
    return (void *)get_int;
}
'''
MAIN = r'''
int main(int argc, char **argv) {
    (void)argc;
    pack = atoi(argv[1]);
    expect_rows = atoi(argv[2]);
    rgb = atoi(argv[3]);
    w2c_env_glReadPixels(NULL, 2, 5, 4, 3, rgb ? 0x1907 : 0x1908, 0x1401, 64);
    assert(calls == (expect_rows ? 3 : 1));
    return 0;
}
'''


class SwitchReadback(unittest.TestCase):
    def test_driver_calls_and_destinations(self):
        cc = shutil.which(os.environ.get("CC", "gcc"))
        self.assertIsNotNone(cc, "a C compiler is required for this regression test")
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "readback.c"
            binary = Path(tmp) / ("readback.exe" if os.name == "nt" else "readback")
            source.write_text(HARNESS + wrapper + MAIN, encoding="utf-8")
            subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-D__SWITCH__", str(source), "-o", str(binary)], check=True)
            for value in (None, "0", "1"):
                for pbo in (0, 1):
                    for rgb in (0, 1):
                        with self.subTest(setting=value, pbo=pbo, rgb=rgb):
                            env = dict(os.environ)
                            env.pop("EIDOS_SWITCH_READPIXELS_ROWS", None)
                            if value is not None:
                                env["EIDOS_SWITCH_READPIXELS_ROWS"] = value
                            subprocess.run([str(binary), str(pbo), str(int(value == "1")),
                                            str(rgb)], env=env, check=True)


if __name__ == "__main__":
    unittest.main()
