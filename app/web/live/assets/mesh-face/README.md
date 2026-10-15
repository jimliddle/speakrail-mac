# Face assets

## 3D motion prototype

`mpfb.glb` is an unchanged copy of the MPFB example avatar from
[TalkingHead](https://github.com/met4citizen/TalkingHead/tree/2afe6d79779313db8909badebf46f9805a6c7b70).
The pinned revision is `2afe6d79779313db8909badebf46f9805a6c7b70`.
The source file is `avatars/mpfb.glb` at that revision.

The upstream README, in its Licenses section, states:

> Example avatar "mpfb.glb" was created using Blender and MPFB Blender
> extension. The avatar is licensed under CC0.

The licence applies to this avatar, not every asset in TalkingHead.
`CC0-1.0.txt` is the unmodified legal text from
https://creativecommons.org/publicdomain/zero/1.0/legalcode.txt.
Credit: met4citizen / TalkingHead, MakeHuman and MPFB contributors.

SHA-256:
`63c645a2a863b9972e9a9c2ed576a1de4c390b8475508e1473e69c87a3ee299c`.

The browser changes materials and framing, and drives the rig's authored
speech and expression morphs. The GLB itself was not edited. No TalkingHead
runtime code or other TalkingHead avatars are included. Three.js and its
loader are vendored separately with their MIT licence.

## Portrait reference

`portrait-reference.png` is the owner's supplied "Emerald Wireframe AI
Face.png", copied without alteration. Its SHA-256 is
`cf8295b6444fe43447973d0f30a0761393f509fb589568485ed9a956060b575f`.
The Portrait appearance projects this image onto the MPFB face using rest-pose
UVs. A separate masked plane preserves its hair silhouette. The source file
is unchanged; all mapping, mouth alignment and blink shading happen at
runtime. This is a frontal approximation, not a fully sculpted 3D likeness.
Plain rig remains available in Settings.

## Earlier sprite trial

`contact-sheet.png` is the 4-column × 6-row character sheet generated at the
repository owner's request on 15 October 2026. It depicts the approved
emerald wireframe woman and contains 15 speech/rest poses, one blink and
eight expressions. It is bundled locally and is not fetched from an image
service at runtime. The earlier renderer cropped the grid and labels in memory
and held the upper face stable while blending speech poses. That renderer is
preserved on the local `trial/mesh-face-sprites-20261015` branch.

The sheet is now a raster reference only. See `mac/LIP_SYNC.md` for the
current timing and quality limitations.
