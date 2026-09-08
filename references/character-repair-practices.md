# Character reference authority, repair scope, and evidence discipline

Read this file when generated supplement views, an existing Blender character, local repair, texture
projection, or ambiguous acceptance evidence is involved.

## Reference authority

Classify each image before modeling:

- **observed canonical**: user-approved source sheet or decoded frame with stable identity and known
  provenance;
- **generated supplement**: a new side, rear, top, or detail view inferred from canonical art;
- **design completion**: an intentionally invented hidden surface approved for construction;
- **unknown**: unsupported or contradictory information that must not be silently invented.

Observed real views control scale, silhouette, visible design, and identity. A generated supplement
can clarify a hypothesis but is not a calibrated projection and may not overrule observed frames.
Record disagreements and use one shared 3D construction to reconcile compatible views. Ask for a
corrected or approved design decision when an identity-defining conflict cannot be reconciled.

## Existing-model and local-repair protocol

1. Inspect the actual current `.blend`, unsaved UI state, references, textures, scripts, Blender
   version, and requested scope before changing anything.
2. Preserve the last user-accepted or visually passing scene as a recoverable baseline. Work in a new
   version; do not overwrite manual edits or resume from a rejected regression.
3. For a local repair, name one responsible part and freeze unrelated geometry, materials, cameras,
   rigs, and accepted proportions. A request to fix hair, face, or one seam does not authorize a
   character-wide redesign.
4. Compare the same fixed cameras before and after. If the named visible defect does not improve, stop
   stacking edits and re-diagnose reference conflict, camera calibration, representation, topology,
   material, UV, or occlusion.
5. Do not let a background Blender process save the same file while an interactive window contains
   unsaved work. Use a separate output path and reopen the exact saved version before review.

## Geometry, texture, and occlusion separation

- Inspect face and hair in clay before accepting projected or painted appearance. Original-image UV,
  baked light, alpha, outline, and emission cannot prove hidden form.
- Diagnose a visible seam or color leak by identifying the responsible evaluated surface, depth,
  material, UV, alpha, and occlusion order. Do not globally scale a part because one view shows a gap.
- Sample UV at the actual hit/interpolated surface region; vertex UVs or face-average UVs can miss
  background crossings inside a face. White or pale hair requires a reviewed mask rather than a
  copied RGB threshold.
- Multiple independently generated textures may contain incompatible lines and highlights. Soft
  blending produces doubles; hard switching produces blocks. Repair geometry/UV boundaries or use a
  coherent atlas instead of making material depend on viewing direction.
- After a local repair, recheck the defect camera, its neighboring views, and the other three cameras
  in the current four-quadrant round.

## Three independent acceptance lanes

- **visual**: silhouette, identity, anatomy, depth, part construction, material/color, and beauty in
  fixed full-resolution views;
- **engineering**: saved/reopened file, dependency availability, finite transforms, topology, normals,
  modifiers, resources, and required intersections/manifold checks;
- **intended use**: actual static presentation, deformation, animation, export/reimport, real-time, or
  print tests requested for delivery.

Passing one lane does not pass another. Report only the uses exercised on the delivered version.
