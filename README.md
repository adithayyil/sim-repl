# sim-repl

```bash
git clone git@github.com:adithayyil/sim-repl.git && cd sim-repl
nix develop

uv run simplay bmp388 play
uv run simplay bmp388 analyze
uv run simplay bmp388 verify
```

| | BME280 | BMP388 |
|---|---|---|
| mutations sampled | 200 | 300 |
| changed something observable | 126 | 99 |
| `L0` | 16 | 33 |
| `L1` | 52 | 43 |
| `L2` | 103 | 73 |
| `L3` | 44 | 54 |
| `L2` or `L3` | 118 | 95 |
| escaped everything | 7 | 4 |
