# Video to 3D

An evidence-driven Codex Agent Skill for turning a fixed-character turntable video or an approved
whole multi-view character sheet into an editable Blender character model.

The workflow measures real source timecodes, extracts 8-72 verified angles, calibrates matching
orthographic cameras, fuses same-angle mask/scale and colour refinement per view, and keeps retopology and Blender
lookdev as separate review gates.

## Highlights

- Accepts a static full-body A-pose orbit video or a whole Front/Back/Left/Right/Top character sheet.
- Includes a reusable MiniMax H3 / H3D H3 IR prompt framework without pre-cutting the sheet.
- Audits uniform rotation against observed source frames and SHA-256 evidence.
- Imports all 8-72 views as calibrated non-rendering Blender overlays before modeling (24 by default).
- Reviews four opposing 90-degree views per round instead of walking through adjacent angles.
- Emits full scanline edge coordinates and pixel/world-unit corrections; silhouette pass requires zero numeric error.
- Produces one fused mask/scale/coordinate/colour review for every angle, plus final review artifacts.
- Rejects per-camera geometry, silent angle reduction, neural-mesh substitution, and unsupported quality claims.

## Install

Clone the repository into your Codex skills directory:

```powershell
git clone https://github.com/enwong93-sketch/video-to-3d.git `
  "$env:USERPROFILE\.codex\skills\video-to-3d"
```

Start a new Codex task after installation so the skill catalogue refreshes.

## Dependencies

- Python 3.10+
- FFmpeg and FFprobe
- Pillow
- NumPy
- Blender

Check the local toolchain:

```powershell
python scripts/turntable_reference.py doctor --blender <path-to-blender.exe>
```

## Use

Ask Codex to use `$video-to-3d` with a turntable video or a whole multi-view character sheet.
The complete operating contract is in [SKILL.md](SKILL.md).

## Output credit

Artifact sets made with this skill must carry this credit in an accompanying README, handoff,
manifest, or other human-readable metadata:

> Made with [Video to 3D](https://github.com/enwong93-sketch/video-to-3d).

The credit does not need to be burned into rendered media or model geometry.

## License

The source code and documentation in this repository are available under the [MIT License](LICENSE).
Linked third-party tools and references remain under their own licenses; their packages are not
redistributed here.
