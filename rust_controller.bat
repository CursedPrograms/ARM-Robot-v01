@echo off
where cargo >nul 2>nul
if not %errorlevel%==0 (
    echo Rust was not found on this system.
    echo Install it from https://rustup.rs/ and re-run this script.
    pause
    exit /b 1
)

cd /d "%~dp0"
cargo run --release --manifest-path scripts\rust_controller\Cargo.toml -- %*
pause
