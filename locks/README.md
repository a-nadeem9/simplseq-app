# Runtime Locks

`linux-64-explicit.txt` is an explicit micromamba lock captured from the
verified v0.1.0-dev Linux/WSL runtime.

The Linux installer uses this lock by default when it is present, then installs
the local app package in editable mode from the extracted release directory.
Set `SIMPLSEQ_USE_LOCK=0` to force solving from `environment.yml`.

macOS currently resolves from `environment.yml`. Add separate `osx-64` and
`osx-arm64` locks after those runtimes have been created and smoke-tested on
real Macs.
