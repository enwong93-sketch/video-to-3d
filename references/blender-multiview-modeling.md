# Blender multi-view modeling

Read this file before creating geometry or changing a calibrated model project.

## Scene contract

- `V3D_REFERENCES` owns the calibrated orthographic cameras and their background images.
- `V3D_MODEL` owns all model geometry; parent it to `V3D_MODEL_ROOT`.
- The root origin is the ground-center of the shared model. Use one global height and unit scale.
- Do not move a reference camera, edit its shift/orthographic scale, crop a source image, or offset a
  model for one view after calibration. Rebuild the alignment contract if the source box was wrong.
- Use the camera whose `v3d_view_id` matches the reference; never compare one yaw against another.

## Per-angle two-layer mask gate

Before geometry work, create one visually admitted reference-character mask per view. At every
retained milestone, render transparent model PNGs from all calibrated cameras. Place each model alpha
mask directly over its same-`view_id` reference mask on one same-sized, same-coordinate canvas.

The overlay is deliberately simple: green means both layers cover the pixel, red means the reference
layer only, and blue means the model layer only. The tool also draws the two bboxes so scale and
position differences are visible. It does not score the result, identify a part, rank an error, or
choose a repair.

The Agent inspects the overlay, compares neighboring yaws, decides whether shared scale or geometry
must change, edits the model, and rerenders. Treat a faulty segmentation mask as an input problem:
correct and re-admit the mask rather than changing the model to fit bad evidence.

## Per-angle fused mask/scale and coordinate/color refinement gate

Keep the camera rig and model transform locked. Render the same model with provisional/final
materials, then fuse mask/scale and coordinate/color evidence on one identical camera pixel canvas.
Pending raw mask evidence does not block generation; it is judged with color for the same angle.

For every angle, inspect the six-panel fused artifact before advancing. Repair in this order:

1. shared geometry or placement when corresponding features land at different coordinates;
2. large value/color blocks and material assignment;
3. roughness, specular response, transparency, normals and shading;
4. UV/texture placement and reference-visible secondary details.

Do not move calibrated cameras, rescale one angle, or use lighting/texture to conceal a geometry
problem. The tool does not score or diagnose the images. Both nested gates and the overall view must
pass; rerender affected neighboring angles after every retained change.

## Retained milestone gates

At every retained milestone, save a versioned `.blend`, render all 8-72 cameras, inspect the saved
renders at full resolution, and reopen the file before continuing. All admitted views must pass the
milestone's relevant checks.

### G0 — coordinate, provenance, and scale lock

Confirm manifest hashes, camera count, exact yaw order, global height, ground plane, root origin,
Blender version, output path, and naming. The fresh-process reference-rig verification must pass.

### G1 — whole-body blockout

Build shared primary masses for head, neck, ribcage, pelvis, arms, legs, hands, and feet. Match total
height, head-to-body ratio, shoulder/hip width, torso depth, limb lengths, stance, and A-pose in every
camera. Use the two-layer mask overlay to see primary-volume scale and coverage differences at every yaw. Reject a
front-only mannequin, flat side depth, or a profile that contradicts diagonals.

### G2 — head, face, and ears

Model skull volume, jaw, cheeks, muzzle/face plane, nose, mouth mass, ears, and neck transition.
Compare front/profile/diagonal/rear silhouettes. Do not use decals or texture alone to fake missing
facial volume.

### G3 — eyes and brows

Build explicit eye volumes, lids, pupils/irises where applicable, brows, and occlusion-safe sockets.
Verify spacing, depth, gaze symmetry, profile projection, and that hair never hides errors in the eye
region.

### G4 — hair as front, side, and rear masses

Separate scalp base, fringe, side locks, rear mass, ponytails/braids, and accessories as needed.
Match the outer silhouette and internal flow at every angle; rear hair cannot be inferred only from
the front image. Thin locks and transparent hair edges must be represented consistently in the
admitted mask policy before comparing the two layers.

### G5 — torso, limbs, hands, and feet

Refine torso depth, joints, limb taper, elbows, knees, wrists, ankles, and anatomical transitions.
Hands are independent geometry with palm volume, thumb placement, and readable fingers. Feet are
independent geometry with heel, arch/instep, toe volume, and sole thickness. Reject mittens, fused
fingers when the design shows separation, pointed blocks, merged shoes, or hidden/cropped extremities.

### G6 — costume, armor, and accessories

Build garment and armor layers with credible thickness, seams, overlaps, closures, and attachment.
Model every asymmetric feature on the correct character side. Inspect gaps, intersections, floating
parts, back construction, and underside/side depth in all corresponding views.

### G7 — topology and materials

Retopologize deliberately for the intended deformation/render use. Preserve silhouette-critical
loops and material boundaries. Never apply an arbitrary vertex-count reduction; choose density from
deformation, silhouette, shading, and target performance requirements, then compare before/after
renders at every angle. Validate normals, watertightness where required, UVs, texel density,
materials, transparency, and NPR/toon behavior.

### G8 — optional rig and deformation

Only when rigging is in scope: apply transforms, build the intended skeleton, skin cleanly, and test
shoulders, elbows, wrists, fingers, hips, knees, ankles, neck, jaw/face controls, hair, costume, and
accessories. The neutral A-pose must still reproduce the reference set after rigging.

### G9 — final every-angle beauty audit

Render the final saved/reopened model from every calibrated camera. For each view, compare reference,
transparent render, the same-coordinate two-layer mask overlay, coordinate/color panel, checkerboard,
ordinary overlay, and difference evidence. Step 7 fused evidence must verify and both nested gates
must carry Agent passes before judging silhouette, scale, proportions, visible design, materials, form
readability, intersections, anatomy, and beauty. Inspect
face, both hands, both feet, hair rear mass, costume seams, and all asymmetry at 100% pixels. Every
per-view `mask_layer_match`, `coordinate_color_match`, and visual gate plus the all-view final audit
must be `pass` with evidence.

## Correction policy

When one angle fails, identify the shared volume causing the disagreement and re-check neighboring
angles after correction. Do not add camera-specific hidden geometry, per-camera shape keys, view
dependent scaling, or presentation tricks that make only one reference line up. When inconsistent
source images cannot be reconciled by one model, fail with the conflicting view IDs and request a
corrected source instead of inventing a compromise and calling it accurate.

Structural checks, camera counts, bbox thresholds, polygon counts, or a green Blender exit code do
not prove visual match. Keep automated and visual conclusions separate.
