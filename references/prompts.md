# Source-generation prompts

Read this file only when a usable source video does not already exist, or when the user asks for
prompts. Keep the user's art direction and source identity authoritative.

## ImageGen multi-view character reference

Use the strongest approved character image or written brief as identity evidence. Generate one
reference sheet containing exact front, back, character-left, and character-right views; add a true
top view when it materially clarifies the design. Do not generate unrelated images.

```text
Create one original adult full-body character reference sheet on one horizontal canvas. Include exact
front, exact back, true character-left profile, and true character-right profile; when requested,
include a fifth true top-down view. Keep a declared fixed order such as Front, Back, Left, Right, Top.
Do not add labels or text when the full sheet will condition a video model, because those marks can be
literalized into the generated video.

All standing views show the exact same character at the exact same scale and pixel height. Use one shared
canvas coordinate system: identical panel width and height, identical ground-line Y coordinate,
identical top-of-head Y coordinate, identical character center X within each panel, identical camera
height, identical orthographic projection, and identical framing. The complete visible character,
hair, hands, fingers, costume extensions, accessories, legs, feet, and soles must remain inside every
panel with at least 8-10% clear margin above, below, left, and right. Do not make one profile or back
view larger, smaller, higher, lower, wider-framed, tighter-framed, or independently centered.

The character holds the same neutral A-pose in every panel, arms slightly away from the torso, elbows
and knees straight but natural, palms readable, all five fingers visibly separated where anatomically
possible, and legs uncrossed. Preserve exactly the same identity, age, facial structure,
head-to-body ratio, body proportions, costume construction, layer thickness, hair shape,
accessories, colors, materials, asymmetry, and left/right placement in all four views.

Use one perfectly uniform flat neutral mid-gray background, approximately #808080, across the entire
multi-view canvas. No gradient, texture, seam, horizon, floor line, cast shadow, vignette, lighting
change, panel border, or different background per view. If true transparency is supported, all four
panels may instead use the same transparent background; never mix transparent and opaque panels.

No perspective foreshortening, three-quarter views, pose change, cropped body parts, extra character,
duplicate limbs, mirrored asymmetry, text, labels, UI, signature, or watermark. Keep panel boundaries
clear and prevent hair, hands, clothing, weapons, or accessories from entering a neighboring panel.
```

After generation, inspect every view at original resolution. Reject or regenerate if any view
changes identity, proportions, costume, hair, accessories, chirality, hand/foot anatomy, ground line,
or scale.

## Whole-sheet local MiniMax H3 input

Keep the accepted multi-view sheet whole. Do not pre-cut Front/Back/Left/Right/Top zones. In H3D,
put the sheet in one character slot and author with `@char1`. Do not hand-write `<Picture N>` or
`<Subject N>`; H3D assigns ordinals and compiles H3 IR.

Use this source framework:

```text
global_prompt:
  2D-animated Japanese anime character-reference video with crisp line art, controlled two-tone cel
  shading, and a clean light palette. @char1 is exactly one <adult identity, hair, face, clothing and
  colours>. Preserve the same age, face, proportions, hairstyle, clothing construction, colours and
  left-right anatomy throughout. The whole sheet defines identity and construction only, not target
  composition. The target contains exactly one centred full-body figure on one seamless neutral
  background. Keep the camera distance, subject scale, centre, lighting, lens, exposure and framing
  fixed. Exclude contact-sheet panels, separators, top-view inset, duplicate bodies, labels, text,
  UI, watermark and unrelated props.
  Audio: N/A
  Music: N/A

shot prompt:
  @char1 stands completely motionless in a neutral thirty-degree A-pose, feet parallel, arms separated
  from the torso, hands open and visible fingers readable. The character does not rotate. The physical
  camera begins at exact front and performs one uninterrupted clockwise Arc Shot through exactly 360
  degrees at constant angular velocity, constant radius and constant eye-level height. It passes every
  intermediate three-quarter, profile and back orientation in order, then reaches the same exact front
  only after the full turn. Preserve identity, pose, scale, centre, lighting and framing. No cut,
  independent pan, zoom, tilt, roll, shake, focal pumping, body motion, expression change, hair or
  cloth motion, easing, acceleration, deceleration, pause, overshoot or reversal.
```

The compiled prompt must contain, in order:

```text
subject_definitions: <Subject 1> is the character shown in <Picture 1>.

retention_analysis: Keep the identity, face and clothing of <Subject 1> consistent across every shot.

detailed_description: ... [Shot 1] ...

overall_soundscape: N/A

non_diegetic_music: N/A
```

The whole-sheet route does not prove that H3 obeyed the requested identity, framing, pose, or timing.
Inspect the generated video, reject panel literalization or multiple characters, and continue with the
measured rotation audit only after the video itself passes the source gate.

## Conditional fixed-coordinate crop

Skip this section for the whole-sheet local MiniMax H3 route. Use it only when the active generation
surface explicitly requires separate image inputs or a downstream evidence task requires individual
standing views.

Preserve the original multi-view sheet unchanged. Split the accepted standing views only by fixed,
declared panel rectangles and declared order. Every standing-view output must have the same pixel
width, same pixel height, same top and bottom crop coordinates, and the same local canvas origin.

Name the four standing-view outputs `front.png`, `back.png`, `character-left.png`, and
`character-right.png`. If a top view exists and is required downstream, record it separately without
forcing it into the standing-view ground-line comparison. Record the source sheet hash plus each fixed
crop rectangle and output hash. Do not use a separate tight
character bounding box for each panel; do not independently resize, rescale, recenter, rotate, warp,
pad, extend, or move any character after cropping. Those operations would destroy the shared scale
and coordinates needed for calibrated camera overlays and visual comparison.

After cropping, place the four standing-view PNGs in a same-sized stack and switch between them. Confirm that the
ground line, head-top position, body height, center line, and safe margins remain consistent. If the
generated panels do not share scale and coordinates, reject/regenerate the sheet instead of repairing
the inconsistency with per-view transforms.

## Absolutely uniform camera-orbit video

Use the accepted whole multi-view sheet as the only character-identity reference. For local MiniMax
H3, provide the complete sheet directly without pre-cutting.

```text
Create one continuous full-body 360-degree camera-orbit reference video around the exact same
character shown in the supplied four-view sheet. The character remains completely motionless in the
same neutral A-pose for the entire clip; the character does not rotate. The physical camera performs
exactly one complete horizontal 360-degree orbit around the character at absolutely uniform camera
rotation speed and constant angular velocity for the entire usable interval.

Mathematically enforce theta(t) = 360 degrees * (t - t0) / T from the exact front view at t0 to the
same exact front view at t0 + T. There must be zero easing, zero acceleration, zero deceleration,
zero pause, zero speed ramp, zero overshoot, zero reversal, zero cut, and zero duplicated or dropped
orientation. The camera must pass the exact profiles, back, and all intermediate angles at their
correct equally spaced times.

Lock camera height, orbit radius, lens/focal behavior, sensor, horizon, pitch, roll, framing, exposure,
lighting, background, and ground plane. No zoom, dolly, pan independent of the orbit, camera shake,
perspective change, parallax drift, crop drift, or focus breathing. Keep the full character, complete
hair, hands, fingers, costume, accessories, legs, and feet visible in every frame with safe margins.
Preserve identity, facial features, body proportions, exact A-pose, clothing construction, materials,
colors, hair topology, accessory placement, asymmetry, and left/right chirality throughout. No body
motion, cloth simulation, hair motion, blinking, expression change, talking, secondary animation,
morphing, extra limbs, disappearing detail, text, UI, logo, or watermark.

Use a clean neutral background and stable diffuse studio lighting that reveals silhouette and form at
every angle. Start with a brief exact-front hold outside the measured interval if needed, perform the
strict constant-speed orbit, and end with a brief exact-front hold only after the full measured turn.
```

The prompt expresses the production requirement; it does not prove compliance. Probe the rendered
video, record real angle observations, and pass `rotation_audit.py`. If it fails, use observed
per-angle anchors or regenerate the video.
