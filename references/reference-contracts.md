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
  "schema": "video-to-3d-model/rotation-observations/v1",
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
  "schema": "video-to-3d-model/angle-anchors/v1",
  "source": {"path": "C:/absolute/source.mp4", "sha256": "..."},
  "anchors": [
    {
      "yaw_deg": 0,
      "timestamp_seconds": 1.25,
      "evidence": {"path": "C:/absolute/anchor-000.png", "sha256": "..."}
    }
  ]
}
```

Continue at exactly `360 / requested_angles` yaw spacing through but not including 360. Evidence
paths and hashes are mandatory; `build` rejects missing, changed, duplicate, uneven, or out-of-range
anchors.

## Blender alignment

Use the full-resolution pixel convention `[left, top, right, bottom]`, with the image origin at the
top-left. Every box must tightly include the complete visible subject, including hair, fingers,
costume extensions, accessories, and soles.

```json
{
  "schema": "video-to-3d-model/alignment/v1",
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

## Reference-character masks

`reference-masks.json` uses schema `video-to-3d-model/reference-masks/v1` and is bound to the exact
`reference-set.json` SHA-256. It contains exactly one full-resolution binary PNG per `view_id`:

- white `255` means a pixel visibly covered by the reference character;
- black `0` means background or a true visible hole between character parts;
- antialiased or translucent source edges are converted with one recorded threshold;
- hair, hands, individual readable fingers, costume extensions, accessories, legs, feet, and soles
  belong in the mask whenever they are visibly present in that angle.

Every mask row records its path, hash, dimensions, bbox, area, method, threshold, review overlay, and
`visual_status`. The manifest also requires reviewer, review time, and an all-mask pass citing every
view. An automatically generated alpha or corner-color mask remains `pending` until its overlay has
been read at full resolution. Reject background leakage, lost thin details, filled arm/leg gaps,
missing transparent design elements, invented hidden surfaces, or any mask that touches a frame edge
because the source itself is cropped.

## Same-coordinate model/reference mask layers

`mask-layer-comparison.json` uses schema `video-to-3d-model/mask-layer-comparison/v2` and binds the
reference set, alignment, render report, and admitted mask manifest by hash. For each `view_id`, the
tool places exactly two binary layers on one canvas:

1. the admitted reference-character mask;
2. the Blender render alpha mask.

Both layers use the same width, height, top-left origin, scale, and pixel coordinates. If the Blender
render uses a proportional resolution percentage, the reference image and mask receive the exact
same resize before layering. Any other canvas mismatch is rejected.

The resulting `mask-layer-overlay.png` uses only three visible states:

- green: both layers cover the same pixel;
- red: reference-mask layer only;
- blue: model-mask layer only.

The companion `mask-layer-overlay-on-reference.png` places the same colors over the source image and
draws the two layer bounding boxes so scale/position differences remain easy to see. The report
stores canvas identity, both raw bboxes, output paths and hashes, plus an empty Agent review field.

The comparison tool does not calculate a similarity score, set a quality threshold, rank regions,
name a defective body part, or prescribe a repair. The Agent inspects the two-layer image, decides
whether scale or geometry differs, checks neighboring angles, performs the repair, and records
`mask_layer_match` as `pass` or `fail` in the independent final review.

## Same-camera coordinate and color projection

`coordinate-color-comparison.json` uses schema
`video-to-3d-model/coordinate-color-comparison/v1`. It is bound by SHA-256 to the reference set,
alignment, Blender render report, and completed Step 5 mask-layer report. Step 6 refuses to start
until every Step 5 `agent_review.status` is `pass`.

For every `view_id`, the reference subject and Blender render are projected onto the exact same
camera-sized pixel canvas with the same top-left origin. The admitted reference mask removes the
source background; the model alpha supplies the model layer. A single corner-derived neutral
background is used for both projections so background pixels do not dominate color comparison.

The tool writes:

- the isolated reference projection;
- the model projection on the same background;
- a 50/50 layer overlay;
- a fixed-coordinate checkerboard alternating reference and model tiles;
- an amplified absolute RGB difference image;
- a four-panel reference/model/overlay/difference image.

The report stores the shared canvas, background color, paths, hashes, and an empty Agent review field.
It deliberately produces no color-similarity score, automatic match verdict, material diagnosis, or
repair prescription. The Agent uses the images to refine shared geometry placement, material
assignment, color/value blocks, roughness/specular response, texture placement, and reference-visible
details, then records `coordinate_color_match` independently.

## Evidence meaning

The manifests prove file identity, source-frame provenance, measured timing, camera calibration, and
that mask and color layers were displayed on the same camera coordinate canvas. They do not decide
whether the visible difference is acceptable or identify what to repair. Likeness, anatomy,
topology, materials, rig quality, and beauty remain Agent visual judgments.
