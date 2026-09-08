# Reference and timing contracts

Read this file when authoring timing observations, non-uniform anchors, or Blender alignment.

## Coordinate convention

- `target_yaw_deg = 0` is the confirmed exact front.
- The one-turn measurement starts at that front and closes at the same front after 360 degrees.
- `direction = clockwise` means video time advances clockwise around the subject as seen from above;
  `counterclockwise` means the reverse.
- Yaw values label real source views. They are not guessed camera extrinsics or generated views.

## Uniform rotation observations

Create `rotation-observations.json`. Use at least eight distinct orientation bands plus the closing
front. Each timecode must come from inspecting a real decoded frame. `rotation_audit.py create`
extracts and hashes those evidence frames.

```json
{
  "schema": "video-to-3d/rotation-observations/v1",
  "source": {},
  "turn": {
    "start_seconds": 1.25,
    "end_seconds": 9.25,
    "front_time_seconds": 1.25,
    "direction": "clockwise"
  },
  "limits": {"max_error_deg": 2.0, "rms_error_deg": 1.0},
  "observations": [
    {"turn_deg": 0, "timestamp_seconds": 1.25},
    {"turn_deg": 45, "timestamp_seconds": 2.25},
    {"turn_deg": 90, "timestamp_seconds": 3.25},
    {"turn_deg": 135, "timestamp_seconds": 4.25},
    {"turn_deg": 180, "timestamp_seconds": 5.25},
    {"turn_deg": 225, "timestamp_seconds": 6.25},
    {"turn_deg": 270, "timestamp_seconds": 7.25},
    {"turn_deg": 315, "timestamp_seconds": 8.25},
    {"turn_deg": 360, "timestamp_seconds": 9.25}
  ]
}
```

Do not copy mathematically ideal timestamps into this file without reading the corresponding source
frames. The observations are the human/agent measurement; the script verifies their residuals and
binds them to decoded evidence.

## Non-uniform per-angle anchors

When uniformity fails, create one real observation for every requested output yaw. Timestamps may be
irregular, but every evidence file must be a decoded source frame with an intact hash.

```json
{
  "schema": "video-to-3d/angle-anchors/v1",
  "source": {"path": "<absolute-source-video>", "sha256": "..."},
  "anchors": [
    {
      "yaw_deg": 0,
      "timestamp_seconds": 1.25,
      "evidence": {"path": "<absolute-evidence-image>", "sha256": "..."}
    }
  ]
}
```

Continue at exactly `360 / requested_angles` yaw spacing through but not including 360. Evidence
paths and hashes are mandatory; `build` rejects missing, changed, duplicate, uneven, or out-of-range
anchors.

The admitted view count must be divisible by four. `analysis_order.strategy` is
`four_quadrant_rounds`: each round contains four `view_id` values separated by exactly 90 degrees.
For 24 views the round offsets are `0°, 45°, 15°, 60°, 30°, 75°`; each offset expands across the four
quadrants. Every downstream Blender, visual-reference, material, and final-review stage preserves
this order.

## Blender alignment

Use the full-resolution pixel convention `[left, top, right, bottom]`, with the image origin at the
top-left. Every box must tightly include the complete visible subject, including hair, fingers,
costume extensions, accessories, and soles.

```json
{
  "schema": "video-to-3d/alignment/v1",
  "reference_set_sha256": "...",
  "target_height_m": 1.7,
  "target_center_z_m": 0.85,
  "camera_distance_m": 8.0,
  "background_alpha": 0.65,
  "max_target_height_drift_pct": 1.0,
  "views": [
    {"view_id": "view-000", "subject_bbox_px": [220, 90, 860, 1820]}
  ]
}
```

Continue with one row for every admitted view. Use one global `target_height_m`; per-view overrides
exist only to detect documented scale drift and must remain within the configured limit. The Blender
setup computes each orthographic scale from the image height and its subject box, solves camera shift
to place the shared model origin at the observed subject center, and records the residual.
`background_alpha` must be 0.05-0.95. The setup imports every view as a `FRONT`/`FIT`, non-rendering
camera reference overlay so the image can be read directly over the model while shaping it.

## Optional reference-character masks

A visually reviewed character mask may be created when background clutter makes the silhouette hard
to read. Keep it bound to the exact source image and inspect hair, fingers, transparent edges,
costume extensions, accessories, feet, and true negative spaces at full resolution.

The mask is only a viewing aid. Do not calculate scanline corrections, convert pixel differences to
Blender movements, require binary equality, or use IoU/XOR/bounding-box values to approve or reject
the model. If segmentation removes a visible feature or leaks background, correct the mask rather
than changing geometry to fit it.

## Detailed per-angle visual evidence

`visual-reference-review.json` uses schema `video-to-3d/visual-reference-review/v1` and binds the
reference set, alignment, Blender render report, saved `.blend`, and evidence images by SHA-256. Each
`view_id` records:

- untouched full-resolution reference;
- neutral model-only render;
- clay render;
- wireframe evidence;
- one or more adjustable-alpha overlay captures;
- full-resolution close-ups for every visible critical part;
- concise observations naming visible agreements, differences, and the shared 3D part changed;
- `pass`, `fail`, or `pending` for `shared_form`, `silhouette`, `proportion_depth`,
  `part_construction`, `visible_design`, `material_color`, and `beauty`.

The review preserves the four-quadrant order. A round closes only after the Agent inspects all four
opposing views and confirms that one shared 3D construction remains convincing across them. Each
status is an explicit visual judgment backed by cited images; no measurement, similarity score, or
automated overlay result may set it.

Reference and render must remain on the calibrated camera canvas so the superimposition is meaningful.
Canvas size, camera count, camera identity, image hashes, and overlay availability are structural
checks only. They prove that the evidence is comparable, not that the model matches.

## Evidence meaning

The manifests prove file identity, source-frame provenance, measured timing, camera calibration, and
that visual evidence belongs to the same view. They do not decide whether a visible difference is
acceptable or identify what to repair. Likeness, anatomy, depth, topology, materials, rig quality,
and beauty remain detailed Agent visual judgments.
