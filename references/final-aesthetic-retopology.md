# Final aesthetic and retopology

Read this file in Step 8. The aesthetic and topology lanes are independent; both must pass.

## Pinned upstream references

### Blender aesthetic and QA lane

Source repository: [arjun988/blender-skills](https://github.com/arjun988/blender-skills) at commit
`8f778d2405a214b508d4c7d80742be8e43acdd52` (MIT).

- [`lookdev/SKILL.md`](https://github.com/arjun988/blender-skills/blob/8f778d2405a214b508d4c7d80742be8e43acdd52/.claude/skills/lookdev/SKILL.md)
- [`qa-review/SKILL.md`](https://github.com/arjun988/blender-skills/blob/8f778d2405a214b508d4c7d80742be8e43acdd52/.claude/skills/qa-review/SKILL.md)
- [`reference-image-match.md`](https://github.com/arjun988/blender-skills/blob/8f778d2405a214b508d4c7d80742be8e43acdd52/.claude/skills/references/reference-image-match.md)
- [`visual-match-checklist.md`](https://github.com/arjun988/blender-skills/blob/8f778d2405a214b508d4c7d80742be8e43acdd52/.claude/skills/references/visual-match-checklist.md)

Do not install or load the full 94-skill pack merely to run this lane. When compatible `lookdev` and
`qa-review` skills from this source are already installed, read them completely. Otherwise use the
self-contained gate below.

### Retopology lane

Source repository: [MushroomFleet/BlenderRetopology-Skill](https://github.com/MushroomFleet/BlenderRetopology-Skill)
at commit `296bd4ac040d5164a5e3ccae0b5f1172e2bc25d7`.

- [Packaged `blender-retopology.skill`](https://github.com/MushroomFleet/BlenderRetopology-Skill/blob/296bd4ac040d5164a5e3ccae0b5f1172e2bc25d7/blender-retopology.skill)
- [Repository overview](https://github.com/MushroomFleet/BlenderRetopology-Skill/tree/296bd4ac040d5164a5e3ccae0b5f1172e2bc25d7)

The pinned repository README says MIT while the repository `LICENSE` file is Apache-2.0. This skill
therefore links and attributes the source rather than redistributing its packaged content. When a
compatible installed copy is available, read it completely; otherwise use the source-backed gate
below. Current task instructions and this project's no-arbitrary-decimation rule override examples
from the upstream package.

## Lane A — retopology gate

### Preserve before changing

- Save and hash the approved high-resolution model in a disabled reference collection.
- Define the target use first: still, cinematic, real-time, facial animation, full-body deformation,
  clothing/hair simulation, and required LODs.
- Set a justified polygon budget from the target. Never inherit a generic decimation ratio.

### Build the retopology

- Work part by part using manual Poly Build/extrusion and shrinkwrap where appropriate.
- Treat face, skull, ears, torso, hands, feet, fingers, eyes/mouth, clothing, hair, armor, and
  accessories as purposeful topology islands.
- Use even loop counts on cylindrical forms and controlled reductions when islands meet. Place poles
  away from visible or high-deformation surfaces.
- Preserve continuous deformation loops around eyes, mouth, jaw, shoulders, elbows, wrists, fingers,
  hips, knees, ankles, neck, and any cloth joint expected to bend.
- Keep density driven by silhouette, deformation and shading. Do not use uniform density everywhere,
  leave n-gons on deforming surfaces, or accept automatic retopology without manual cleanup for a
  hero character.

### Validate retopology

- Compare high-resolution and retopologized silhouettes in every calibrated camera.
- Inspect wireframes at front, profiles, back, diagonals, face, hands, feet and dense costume areas.
- Check normals, manifold state, duplicate/loose geometry, intersections, pole placement, edge length,
  UV readiness, material boundaries, and the actual polygon budget.
- If animation is required, test representative shoulder, elbow, wrist/finger, hip, knee, ankle,
  neck, face, hair and garment deformation before approval.
- Rerun Steps 6-7 after every topology, normal, UV, material, texture-placement, or visible-color change.

The retopology verdict is `PASS` only when topology requirements and the renewed Step 7 fused evidence
both pass. A clean wireframe that changes the approved silhouette is a failure.

## Lane B — Blender aesthetic and QA gate

### Form and neutral lookdev

1. Render a clay/grey pass under a neutral evaluation rig. Form, silhouette and depth must read before
   textures or beauty lighting.
2. Apply base materials and compare large value/color groups with Step 7 fused evidence.
3. Check edge highlights, roughness/specular response, controlled emissive values, transparency,
   normals and material separation. Materials may not disguise missing geometry.

### Beauty lookdev

1. Lock an explicit neutral rig and a separate beauty rig; do not overwrite calibrated reference
   cameras.
2. Adjust only one major category per retained iteration: material, light, or camera/presentation.
3. Capture every-angle screenshots/renders, write a short gap list, fix, and recapture. Stop after a
   bounded three-to-five iterations unless a new evidenced defect appears.
4. Check grayscale value readability, palette fidelity, highlight control, edge separation, face and
   eye readability, hand/foot readability, hair mass, costume layering, material response, and
   asymmetric details.

### Final QA verdict

Record one of `SHIP`, `SHIP WITH NOTES`, or `NO-SHIP`, backed by:

- all calibrated angle renders;
- hero three-quarter and profile views;
- neutral/clay and material/light beauty views;
- wireframe/topology evidence;
- reference-versus-render comparisons from the Step 7 fused per-angle review;
- blocker, major, minor and optional findings;
- rerun evidence after every blocker/major fix.

The aesthetic verdict cannot override a topology or Step 7 fused-review failure. A technically clean mesh
also cannot override an aesthetic `NO-SHIP` verdict.
