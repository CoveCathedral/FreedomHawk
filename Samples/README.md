# Samples

Put your **own** drum kits here to use them in the Drum Looper. Each kit is a folder of
part subfolders (`KICK/`, `SNARE/`, `HIHAT/`, …) containing `.wav` files:

```
Samples/
└── My Kit/
    ├── KICK/    kick.wav
    ├── SNARE/   snare.wav
    ├── HIHAT/   hat.wav
    └── 808/     808.wav
```

Kit folders placed here show up automatically in the Drum Looper's **Kit** dropdown.
See [`docs/drum-kits.md`](../docs/drum-kits.md) for the full list of recognised part
names and supported formats.

## Not committed

Everything in this folder **except this README is git-ignored**. Third-party drum kits are
usually copyrighted, so they stay on your machine and are never uploaded or redistributed.
The app ships only its built-in synthesized kit; it does not bundle any third-party audio.
