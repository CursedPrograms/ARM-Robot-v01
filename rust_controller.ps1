# rust_controller.ps1 - the Rust controller. Buddies: rust_controller.bat, rust_controller.sh.
Set-Location $PSScriptRoot
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) { Write-Host "Rust was not found. Install it from https://rustup.rs/"; exit 1 }
cargo run --release --manifest-path scripts\rust_controller\Cargo.toml -- @args
exit $LASTEXITCODE
