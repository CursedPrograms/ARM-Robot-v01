//go:build windows

package main

import "syscall"

// openLibrary loads a DLL; purego.RegisterLibFunc then resolves symbols in it.
func openLibrary(name string) (uintptr, error) {
	h, err := syscall.LoadLibrary(name)
	return uintptr(h), err
}
