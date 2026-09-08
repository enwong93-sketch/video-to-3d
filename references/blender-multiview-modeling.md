# Blender multi-view modeling

Read this file before creating geometry or changing a calibrated model project.

## Scene contract

- `V3D_REFERENCES` owns the calibrated orthographic cameras and their background images.
- `V3D_MODEL` owns all model geometry; parent it to `V3D_MODEL_ROOT`.
- Every admitted camera owns exactly one front-depth alpha reference overlay. It is non-rendering
  camera data, not a plane or mesh, and remains outside `V3D_MODEL`.
- The admitted view count, calibrated camera count, and reference-overlay count must be identical.
  The default is 24/24/24; do not start modeling with missing overlays.
- The root origin is the ground-center of the shared model. Use one global height and unit scale.
- Do not move a reference camera, edit its shift/orthographic scale, crop a source image, or offset a
  model for one view after calibration. Rebuild the alignment contract if the source box was wrong.
- Use the camera whose `v3d_view_id` matches the reference; never compare one yaw against another.

## Version and save contract

- Preserve the last visually accepted scene before a substantial or local repair. Work in a new
  version and freeze unrelated user-authored geometry, materials, cameras, rigs, and proportions.
- Treat script completion, file existence, and viewport appearance as separate facts. Blender batch
  work must use a non-zero Python exit code on exceptions and stop dependent renders after failure.
- Never let a background process save the same `.blend` while an interactive Blender window contains
  unsaved work. Write a separate candidate, reopen that exact file, and generate evidence from the
  reopened scene.
- Bind input scene, script, reference set, candidate `.blend`, and renders by path/version/hash when
  several iterations coexist. Hashes identify evidence; they do not score visual similarity.

## In-Blender overlay gate

Before creating character geometry, switch through every calibrated camera and confirm that the
matching source image is visibly superimposed at the calibrated scale and shift. The overlay uses
front depth plus controlled alpha so reference edges and model edges can be read simultaneously;
it must not render and must not intersect the character as geometry. Fresh reopen verification must
confirm image hash, `FRONT` depth, `FIT` framing, alpha, collection isolation, and one overlay for
every admitted `view_id`. Any failure blocks modeling.

## Four-quadrant modeling order

Never shape the model by walking through adjacent yaws. Process four overlays separated by 90
degrees in each round, reconcile the shared model across all four, then advance. For 24 views use:

1. `0/90/180/270`
2. `45/135/225/315`
3. `15/105/195/285`
4. `60/150/240/330`
5. `30/120/210/300`
6. `75/165/255/345`

The cardinal round locks height, ground, front/back width and side depth. The diagonal round exposes
false symmetry and depth transitions. Intermediate rounds refine continuous volume without allowing
one locally adjacent view to drag scale or proportion away from the opposing views. Recheck every
completed round after a retained change to overall scale, body proportion, or any large shared form.

## Per-angle detailed visual-reference gate

At every retained milestone, switch to each calibrated camera and compare the reference directly
against the same shared model. Use reference-only, model-only, clay, wireframe, and adjustable-alpha
superimposition; capture close-ups wherever the full-body view cannot show construction clearly.

Inspect the visible form rather than a score: silhouette flow, landmark placement, depth, curvature,
plane changes, joints, negative spaces, layer thickness, attachment, asymmetry, and part identity.
Name the defective 3D part before editing it. Correct the shared mesh by eye, then inspect the other
three opposing cameras in the current round before retaining the change.

Optional masks can isolate a busy silhouette, but they cannot decide whether geometry passes. Do not
calculate or follow pixel/world-unit edge corrections, chase exact binary equality, or let IoU, XOR,
bbox, scanline, or similarity values prescribe vertex movement. Treat a faulty reference or mask as
an input problem instead of deforming the model to fit it.

Keep the camera rig and model transform locked. Correct form before material, then compare large
value/color blocks, roughness, specular response, transparency, normals, shading, UV placement, and
visible secondary details in the same views. Do not use lighting or texture to conceal missing depth
or construction. Rerender the affected angle and all other views in its round after every retained
change.

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
camera. Use adjustable-alpha overlays, clay views, and opposing cameras to judge primary-volume scale
and coverage at every yaw. Reject a
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
the front image. Judge thin locks and transparent hair edges from full-resolution reference, clay,
wireframe, and overlay close-ups rather than forcing them into a binary outline.

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

Render the final saved/reopened model from every calibrated camera. For each view, compare the
full-resolution reference, neutral render, clay, wireframe, adjustable-alpha overlay, and critical
part close-ups. Judge silhouette, scale, proportions, depth, construction, visible design, materials,
form readability, intersections, anatomy, and beauty together. Inspect
face, both hands, both feet, hair rear mass, costume seams, and all asymmetry at native 100% zoom. Every
per-view visual status plus the all-view final audit must be `pass` with cited evidence and written
observations.

## Correction policy

When one angle fails, identify the shared volume causing the disagreement and re-check neighboring
angles after correction. Do not add camera-specific hidden geometry, per-camera shape keys, view
dependent scaling, or presentation tricks that make only one reference line up. When inconsistent
source images cannot be reconciled by one model, fail with the conflicting view IDs and request a
corrected source instead of inventing a compromise and calling it accurate.

Structural checks, camera counts, bbox values, polygon counts, similarity metrics, or a green Blender
exit code do not prove visual match and may not drive modeling. Keep automated and visual conclusions
separate.
