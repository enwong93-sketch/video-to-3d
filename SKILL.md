---
name: video-to-3d
description: Turn a single-character A-pose orbit video or an approved whole multi-view character sheet into an editable Blender model using the local MiniMax H3 MAIN and H3 IR turntable generation when needed, measured 8-72 angle evidence, calibrated reference cameras, fused per-angle mask/scale and coordinate/color refinement, source-backed retopology and Blender lookdev/QA, and every-angle beauty review. Use for fixed-subject character turntables and Blender reconstruction; do not use for action footage, moving subjects, direct neural-mesh generation, or photogrammetry capture.
license: MIT
metadata:
  version: 1.7.0
  default_angles: 24
  tested_blender: 5.1.0
---

# Video to 3D

Build an editable Blender character from source-backed angle evidence. Treat the video as a measured
view set, not as a magical multi-view reconstruction input. The finished `.blend`, calibrated
cameras, reference images, model parts, and review evidence remain inspectable and reproducible.

## Non-negotiable outcome

- Use 8-72 independently decoded real source angles; default to 24. Use more only when the video has
  enough sharp, identity-stable frames.
- Establish true view angles from observed timecodes. A prompt that asks for constant speed is not
  proof that the resulting video is constant-speed.
- Import every admitted view into Blender on its matching calibrated orthographic camera. One global
  model scale and origin must serve every camera.
- At every retained geometry milestone, compare silhouette, scale, proportions, and visible design
  against the corresponding reference at every admitted angle.
- At every admitted angle, place the visually approved reference-character mask and Blender render
  alpha mask on the same-sized canvas at identical pixel coordinates. Show overlap, reference-only,
  and model-only pixels; leave interpretation and repair decisions to the Agent.
- For each angle, review mask/scale/position and coordinate/color/material evidence together before
  advancing. Never finish all mask angles first and postpone color to a separate batch.
- Treat retopology and Blender aesthetic/QA as two independent Step 8 gates. Rerun fused evidence
  after topology, material, UV, normal, or visible look changes.
- Finish with a full-resolution beauty audit across every angle. Numeric checks support but never
  replace visual judgment.
- Do not route geometry generation through IMG2 Three.js, a neural 3D service, a point cloud, a
  splat, or independent per-frame meshes.

## Attribution

Every delivered artifact set made with this skill must include this credit in its accompanying
README, handoff, manifest, or other human-readable metadata:

`Made with [Video to 3D](https://github.com/enwong93-sketch/video-to-3d).`

Do not burn the credit into images, video, audio, or model geometry unless the user requests visible
on-media attribution.

## Dependencies

Run the local scripts with Python 3.10+; `ffmpeg`, `ffprobe`, Pillow, NumPy, and Blender are required. Start
with:

```powershell
python scripts/turntable_reference.py doctor --blender <path-to-blender.exe>
```

Do not install a cloud fallback. If Blender is not on `PATH`, pass its exact executable path.

## 1. Produce or accept the source

If the user has no approved source art, read [prompt templates](references/prompts.md). First create
one identity-locked multi-view specification sheet with exact front, back, character-left, and
character-right views; add a true top view when it materially clarifies hair, shoulders, accessories,
or depth. Use that sheet as the only canonical character reference for the orbit-video prompt. Keep
the original source, generation settings, and rights/provenance beside the project.

When the target is the installed local MiniMax H3 workflow, provide the accepted complete multi-view
sheet as one whole character reference. Do not pre-cut its Front/Back/Left/Right/Top zones. In H3D,
place the sheet in a character slot, author with `@char1`, and use the reusable H3 IR framework in
[prompt templates](references/prompts.md). Let H3D assign reference ordinals.

Split a sheet only when the active generation surface explicitly requires separate image inputs or
when separate panels are needed for a downstream evidence task. In that case, preserve one canvas
coordinate system and identical scale, use fixed declared panel boundaries, and never resize or
recenter panels independently. Always retain and hash the original whole sheet.

Accept only one static full-body character in a neutral A-pose with visible fingers and feet, stable
identity, costume, hair, accessories, lighting, lens, camera height, distance, framing, and
background. Reject action motion, pose change, crop drift, identity drift, an incomplete turn, or a
moving/zooming lens.

## 2. Probe and measure the turn

Extract an overview into a new directory:

```powershell
python scripts/turntable_reference.py probe <video> --out <work>\turntable-probe --frames 64
```

Read every probe frame at original resolution. Identify the first exact front, the closing exact
front after one full turn, direction, and at least eight distinct observed orientation bands. Record
those observations using the schema in [reference contracts](references/reference-contracts.md),
then create the evidence-backed rotation audit:

```powershell
python scripts/rotation_audit.py create `
  --video <video> --observations <rotation-observations.json> `
  --out <work>\rotation-audit.json --max-error-deg 2 --rms-error-deg 1
```

The audit extracts and hashes the source frame for every observation and recomputes residuals against
`theta(t) = 360 * (t - t0) / T`. Uniform mapping is admitted only when the audit passes. If the
motion accelerates, eases, pauses, overshoots, reverses, or was edited, do not loosen the thresholds
to force a pass; record one observed source timecode and evidence frame for every requested angle.

## 3. Build and visually admit 8-72 real views

Uniform audited source:

```powershell
python scripts/turntable_reference.py build <video> `
  --out <work>\reference-set --rotation-audit <work>\rotation-audit.json `
  --angles 24 --candidates 1
```

Non-uniform source:

```powershell
python scripts/turntable_reference.py build <video> `
  --out <work>\reference-set --anchors-json <angle-anchors.json> `
  --start <seconds> --end <seconds> --front-time <seconds> `
  --direction clockwise --angles 24 --candidates 1
```

Default to `--candidates 1` so the admitted timestamp stays at the observed angle. If blur requires a
local search, keep `--candidate-yaw-radius-deg` at or below 0.5 degrees and retain every candidate,
timestamp, offset, and hash.

Open every admitted PNG at full resolution. Complete `review.json` using only `pass`, `fail`, or
`pending`, cite every relevant `view_id`, and then run:

```powershell
python scripts/turntable_reference.py verify `
  --reference-set <work>\reference-set\reference-set.json `
  --review <work>\reference-set\review.json
```

Any failed or pending source gate is a hard stop. A valid manifest or green extraction command is not
visual acceptance.

## 4. Import all angles, calibrate cameras, and build the shared rough model

Read [Blender multi-view modeling](references/blender-multiview-modeling.md). Create
`alignment.json` with one full-resolution subject bounding box for every view and one global target
height. Every view ID must be present exactly once.

Create a new Blender project:

```powershell
<blender.exe> --factory-startup --background --python-exit-code 2 `
  --python scripts/blender_reference_setup.py -- `
  --reference-set <work>\reference-set\reference-set.json `
  --alignment <work>\alignment.json --blend-out <work>\character-model.blend `
  --report <work>\blender-setup.json --clear-scene
```

The script creates `V3D_REFERENCES`, `V3D_MODEL`, `V3D_MODEL_ROOT`, one orthographic camera per real
angle, one hashed camera background per view, and calibrated scale/shift metadata. Reopen the saved
file in a fresh Blender process and verify rather than trusting the save call:

```powershell
<blender.exe> <work>\character-model.blend --background --python-exit-code 2 `
  --python scripts/blender_reference_setup.py -- `
  --reference-set <work>\reference-set\reference-set.json `
  --alignment <work>\alignment.json --verify-only `
  --report <work>\blender-reopen-verification.json
```

Only after the fresh reopen passes, build one shared rough model in `V3D_MODEL`, parented to
`V3D_MODEL_ROOT`. Read [Blender multi-view modeling](references/blender-multiview-modeling.md) and
block the full character part by part: whole-body proportions, head/face/eyes, front-side-rear hair,
torso and limbs, independent hands/fingers, independent feet/soles, costume, armor, and accessories.
Use every admitted camera while shaping the same geometry. Do not make camera-specific meshes,
per-view scale corrections, or a front-only mannequin and call the rough model complete.

## 5. Prepare reviewed reference masks

This step compares the rough/refined model with each corresponding angle without replacing the
Agent's judgment. Read the mask contract in [reference contracts](references/reference-contracts.md).

First create one full-resolution binary character mask for every admitted reference. Prefer source
alpha when it genuinely isolates the character; otherwise supply reviewed segmentation masks.
`corner-color` is only a draft helper for a clean, near-uniform background.

```powershell
python scripts/occlusion_mask_test.py masks `
  --reference-set <work>\reference-set\reference-set.json `
  --out <work>\reference-masks --mode alpha
```

Inspect every cyan mask overlay at full resolution. Correct background leakage, lost hair/fingers/
accessories, filled gaps, and cropped edges; then set the manifest, every `visual_status`, reviewer,
and review time to `pass`.

## 6. Generate same-angle mask and scale evidence

Render the current shared model through every calibrated camera, then place the reference mask and
model alpha mask on one same-sized canvas at identical pixel coordinates:

```powershell
<blender.exe> <work>\character-model.blend --background --python-exit-code 2 `
  --python scripts/blender_render_views.py -- `
  --out <work>\step6-renders --report <work>\step6-render-set.json

python scripts/occlusion_mask_test.py compare `
  --reference-set <work>\reference-set\reference-set.json `
  --alignment <work>\alignment.json --render-report <work>\step6-render-set.json `
  --reference-masks <work>\reference-masks\reference-masks.json `
  --out <work>\step6-mask-layers
```

These mask layers are evidence inputs for Step 7. Do not approve every mask as a separate batch
before looking at color.

## 7. Fuse mask/scale and coordinate/color refinement per angle

Keep every calibrated camera, orthographic scale, shift, render resolution, root transform, and
character pose locked. Pending Step 6 mask reviews do not block this command because both evidence
types must be judged together for the same angle.

Project the reference image and Blender render onto the exact same camera pixel canvas:

```powershell
python scripts/fused_multiview_compare.py compare `
  --reference-set <work>\reference-set\reference-set.json `
  --alignment <work>\alignment.json --render-report <work>\step6-render-set.json `
  --mask-layer-report <work>\step6-mask-layers\mask-layer-comparison.json `
  --out <work>\step7-fused-multiview
```

The script produces one six-panel fused image per `view_id`: mask overlap, mask on reference,
reference color, model color, 50/50 color overlay, and amplified color difference. It retains the
standalone evidence and does not score similarity or decide what to repair.

Process one angle as one unit before moving to the next:

1. Read the red/blue mask edges and repair shared scale, position, silhouette, missing volume, or
   extra volume without moving the calibrated camera.
2. On that same angle, compare feature coordinates and value/color blocks for skin, hair, eyes,
   costume, armor, and accessories.
3. Correct materials and visible details without hiding geometry errors with lighting or texture.
4. Rerender the changed angle and neighboring angles, regenerate both evidence types, and repeat.
5. Set `agent_review.mask_scale.status` and `agent_review.coordinate_color.status` to `pass`; only
   then set the row's overall `agent_review.status` to `pass` with notes.

The report is `fused-multiview-comparison.json`. A view cannot pass while either nested gate is
pending or failed. Never review all mask panels first and all color panels afterward.

Concept art and a Blender render need not be literally pixel-identical when their lighting model or
stylization differs. "Pass" means the Agent has explained or corrected every material difference
relevant to the requested model; do not claim mathematical equality from a visual overlay.

For anime/NPR characters, load `$build-anime-npr-character` as a part-craft supplement when
available. Its artistic part gates supplement this workflow; the measured cameras and every-angle
evidence remain authoritative.

## 8. Retopology, Blender aesthetic review, and final audit

Read [final aesthetic and retopology](references/final-aesthetic-retopology.md). It pins and
attributes the selected upstream sources and converts them into two separate lanes; one never counts
as passing the other.

### 8A. Retopology lane

Use the manual, deformation-aware workflow derived from
`MushroomFleet/BlenderRetopology-Skill`: preserve the approved high-resolution model, decide the
actual delivery/rig requirements and polygon budget, build feature-based topology islands with
manual/shrinkwrap methods, connect them with controlled edge-flow reductions, and validate loops at
face, shoulders, elbows, wrists, fingers, hips, knees, ankles, neck, clothing, hair, and accessories.
Do not apply the source's example decimation ratio as a universal rule and do not auto-remesh a hero
character without manual cleanup.

After topology, UV, material, normal, or visible look changes, rerender every calibrated angle and
rerun Steps 6-7. Retopology is not accepted until every fused per-angle review passes again.

### 8B. Blender aesthetic and QA lane

Use the `lookdev` plus `qa-review` workflow from `arjun988/blender-skills`: clay/grey form check,
base materials, neutral evaluation light, beauty light, screenshot comparison, written gap list,
bounded refinement, and explicit final verdict. Lighting and grading may improve presentation only
after geometry and material correspondence are already correct; never use them to hide a Step 7 failure.

Produce the final render set, final Step 6 mask layers, and final Step 7 fused multiview report.
Use new output directories for every retained iteration:

```powershell
<blender.exe> <work>\character-model.blend --background --python-exit-code 2 `
  --python scripts/blender_render_views.py -- `
  --out <work>\final-renders --report <work>\final-render-set.json

python scripts/occlusion_mask_test.py compare `
  --reference-set <work>\reference-set\reference-set.json `
  --alignment <work>\alignment.json --render-report <work>\final-render-set.json `
  --reference-masks <work>\reference-masks\reference-masks.json `
  --out <work>\final-mask-layers
```

Immediately fuse the final mask layers with color evidence; do not approve masks separately:

```powershell
python scripts/fused_multiview_compare.py compare `
  --reference-set <work>\reference-set\reference-set.json `
  --alignment <work>\alignment.json --render-report <work>\final-render-set.json `
  --mask-layer-report <work>\final-mask-layers\mask-layer-comparison.json `
  --out <work>\final-fused-multiview
```

Inspect each final fused panel angle by angle. Both nested statuses and the overall row status must
pass for every admitted angle. Then prepare the independent final review:

```powershell
python scripts/angle_review.py prepare `
  --reference-set <work>\reference-set\reference-set.json `
  --alignment <work>\alignment.json --render-report <work>\final-render-set.json `
  --mask-layer-report <work>\final-mask-layers\mask-layer-comparison.json `
  --fused-multiview-report <work>\final-fused-multiview\fused-multiview-comparison.json `
  --out <work>\final-angle-review
```

Inspect every full-resolution angle plus face, hands, feet, hair, costume seams, materials, wireframe,
deformation-critical loops, and every asymmetric feature. Mark `mask_layer_match`,
`coordinate_color_match`, `silhouette_match`, `proportion_match`, `scale_match`, `visual_match`, and
`beauty` for every view. Record a separate retopology verdict and aesthetic/QA verdict, then run:

```powershell
python scripts/angle_review.py verify `
  --review <work>\final-angle-review\every-angle-review.json
```

Deliver only when source verification, reference-mask admission, fresh Blender reopen, Step 7 fused
per-angle review, retopology, aesthetic/QA, every-angle review, and final beauty audit all pass. Keep the editable
`.blend`, high-resolution backup, retopologized mesh, wireframes, manifests, masks, hashes,
full-resolution renders, overlays, color comparisons, and verdicts together.

## Fail closed

Stop with the exact failed gate and smallest required new input when the source is unreadable,
uniformity evidence fails, per-angle anchors are incomplete, any view/hash changes, alignment is
missing, a reference mask is unreviewed, mask inputs change, Blender reopen differs, the shared model
cannot satisfy the angle set, or any mask-layer/coordinate-color/topology/aesthetic/visual/beauty
status remains `pending` or `fail`. Do
not silently reduce the angle count, replace real views with generated ones, let the overlay script
make the Agent's repair decision, or call file-integrity success a likeness or beauty pass.
