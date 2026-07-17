# Tone data (generated locally — not in the repository)

This folder holds the Firehawk tone model — the amp/cab/effect/reverb models, their
parameters and ranges, the catalogs, the default preset, and the symbol table.

Those files are **Line 6's data**, so FreedomHawk does not redistribute them. Instead you
generate this folder from an APK of the (discontinued) Firehawk Remote app that you
lawfully have, with:

```
python tools/extract_assets.py path/to/firehawk-remote.apk
```

(If the APK sits in the project root as `com-line6-firehawk-*.apk`, you can omit the path.)

After running it, this folder will contain the `*.models`, `*Catalog.json`,
`default_preset.json`, `defaultSymbolTable.bin`, and a regenerated `firehawk_symbols.json`,
and the app will run. Everything here except this README is git-ignored.
