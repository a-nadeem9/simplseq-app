# Runtime Locks

Runtime lock files are generated release artifacts for verified platforms.

The Linux installer uses `linux-64-explicit.txt` by default when it is present,
then installs the local app package in editable mode from the extracted release
directory. Set `SIMPLSEQ_USE_LOCK=0` to force solving from `environment.yml`.

Regenerate `linux-64-explicit.txt` after dependency changes before publishing a
Linux release. It is intentionally not hand-edited because explicit locks pin
the full resolved runtime, not just the top-level packages.

macOS currently resolves from `environment.yml`. Add separate `osx-64` and
`osx-arm64` locks after those runtimes have been created and smoke-tested on
real Macs.
