//go:build !windows

package main

import "github.com/ebitengine/purego"

// openLibrary loads a shared library; purego.RegisterLibFunc then resolves symbols in it.
func openLibrary(name string) (uintptr, error) {
	return purego.Dlopen(name, purego.RTLD_NOW|purego.RTLD_GLOBAL)
}
