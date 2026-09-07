# Video to 3D Model

An evidence-driven Codex Agent Skill for turning a fixed-character turntable video or an approved
whole multi-view character sheet into an editable Blender character model.

The workflow measures real source timecodes, extracts 8-72 verified angles, calibrates matching
orthographic cameras, compares same-coordinate masks and colour, and keeps retopology and Blender
lookdev as separate review gates.

## Highlights

- Accepts a static full-body A-pose orbit video or a whole Front/Back/Left/Right/Top character sheet.
- Includes a reusable MiniMax H3 / H3D H3 IR prompt framework without pre-cutting the sheet.
- Audits uniform rotation against observed source frames and SHA-256 evidence.
- Builds 8-72 same-scale Blender reference cameras around one shared model origin.
- Produces reference masks, silhouette layers, coordinate/colour comparisons, and every-angle review artifacts.
- Rejects per-camera geometry, silent angle reduction, neural-mesh substitution, and unsupported quality claims.

## Install

Clone the repository into your Codex skills directory:

```powershell
git clone https://github.com/enwong93-sketch/video-to-3d-model.git `
  "$env:USERPROFILE\.codex\skills\video-to-3d-model"
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
python scripts/turntable_reference.py doctor --blender C:\path\to\blender.exe
```

## Use

Ask Codex to use `$video-to-3d-model` with a turntable video or a whole multi-view character sheet.
The complete operating contract is in [SKILL.md](SKILL.md).

## Output credit

Artifact sets made with this skill must carry this credit in an accompanying README, handoff,
manifest, or other human-readable metadata:

> Made with [Video to 3D Model](https://github.com/enwong93-sketch/video-to-3d-model).

The credit does not need to be burned into rendered media or model geometry.

## License

The source code and documentation in this repository are available under the [MIT License](LICENSE).
Linked third-party tools and references remain under their own licenses; their packages are not
redistributed here.
