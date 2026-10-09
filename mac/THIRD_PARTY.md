# Third-Party Terms

This is a practical inventory, not a replacement for the applicable licences.
The original root `NOTICE` remains authoritative for upstream attributions.

| Component | Source terms / distinction |
| --- | --- |
| Speakrail controller and UI | Apache-2.0; original notices retained |
| This Mac adapter and launcher code | Apache-2.0 |
| Speakrail audio.cpp fork | Apache-2.0; bundled dependencies have their own notices |
| Breeze Mac serving fork | Apache-2.0 source; separate from model licence |
| MLX, MLX-LM and MLX-Audio | MIT; installed separately, see their distributions |
| Gemma, Speakrail adapter, Voxtral and turn head | Downloaded separately via the pinned upstream manifest; retain model-publisher terms |
| Breeze TTS 2 MLX weights, derivatives, outputs | BreezeBlue Research and Non-Commercial License, not Apache-2.0 |
| Upstream `app/voices/female_a.wav` | Synthetic Breeze output; same research/non-commercial terms |
| Open-Meteo weather data | CC BY 4.0; credit Open-Meteo.com |
| Onest typography | Original browser Google Fonts resource; no font files added |

The included `licenses/BREEZE-MODEL-LICENSE.txt` is an unmodified copy from
the tested model snapshot. It restricts commercial deployment and generated
audio usage, not merely resale of the weights. Obtain a separate licence
from BreezeBlue before a commercial deployment requiring those rights.

Sources:

- https://github.com/speakrail/speakrail/blob/main/NOTICE
- https://github.com/speakrail/audio.cpp/tree/ba2ae40d4630874121d2dfadddd10fe97c358b89
- https://github.com/Shoofio/breeze-tts2-fast-streaming-api/tree/f1818ec44da33302701718e5fb15267ce1cf5e4f
- https://huggingface.co/mlx-community/Breeze-TTS-2-mlx-8bit/tree/c6e4a2ff6ab9afba68b7853de802273ffe23fb49
- https://github.com/ml-explore/mlx
- https://github.com/ml-explore/mlx-lm
- https://github.com/Blaizzy/mlx-audio

Model weights and newly generated audio are intentionally excluded from this
fork. Retaining the code's Apache licence does not remove model/output terms.
