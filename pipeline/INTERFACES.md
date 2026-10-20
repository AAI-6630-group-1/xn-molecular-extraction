# Proposed file contract version 0.1

Use UTF-8. CSV files always have headers; empty JSONL files mean zero records.
Use JSON `null` or an empty CSV field for unavailable values, never a fabricated
zero confidence. `run.json` records exact package/model versions, configuration,
commit/dirty state, hardware, runtime and PDF SHA-256. This proposal is not frozen.

## Conventions

- `paper_id` is a string; keep course IDs 1, 2, 4, 6, 16 and 19. `page` starts at 1.
- `x0,y0,x1,y1` are PDF points, top-left origin, unrotated crop-relative coordinates
  as returned by PyMuPDF text extraction. Pages store `pixel_to_pdf=[a,b,c,d,e,f]`:
  `x'=a*x+c*y+e`, `y'=b*x+d*y+f`. Transform all four box corners before taking
  min/max. Keep separate `crop_bbox` coordinates if padding enlarges a detection.
- IDs are unique per run. Preserve `box_id` through every reader and downstream
  record. A reader returns one result per requested crop, including abstentions;
  a count mismatch is an error, never a zip that silently drops records.
- A missing file is an error. Empty output is valid only when its producer is
  `complete` with zero records or explicitly `stub` in a smoke run.
- Reader confidences are not calibrated against each other. Preserve their
  identities and individual scores rather than averaging them as probabilities.

## Records

Every per-paper record includes `paper_id`; coordinate-bearing records include
`page`. References must resolve within the same run and paper.

| File | Required fields | Meaning |
|---|---|---|
| `pages.jsonl` | `paper_id,page,image_path,width_px,height_px,width_pt,height_pt,rotation,dpi,pixel_to_pdf` | Point dimensions describe the displayed page; transform yields unrotated coordinates. |
| `text.jsonl` | `paper_id,page,block_id,x0,y0,x1,y1,text,source` | `source=pdf_text` or future `ocr`. A scan may have no text blocks. |
| `regions.csv` | `paper_id,page,box_id,x0,y0,x1,y1,crop_path,role,gate,confidence,reason` | `role=molecule/scaffold/substituent/unknown`; `gate=molecule/non_molecule/uncertain`. Rejected regions may have no crop. |
| `tables.jsonl` | `paper_id,page,table_id,bbox,scaffold_box_id,columns,rows,status,reason` | Front end supplies geometry/raw cells. `scaffold_box_id` may be null. Columns: `column_id,heading`; rows: `row_id,label,cells`; cells: `cell_id,column_id,text,box_id,bbox,evidence_block_ids`. Nullable fields remain present. |
| `readings.csv` | `paper_id,box_id,reader,smiles,confidence,raw,status,reason` | Same reader keys as `benchmarks/readers.py`. One row per `(box_id,reader)`; optional `reader=consensus` names its policy in metadata. |
| `links.jsonl` | `paper_id,link_id,box_id,label,table_id,row_id,evidence_block_ids,status,reason` | Label/table/row may be null. Ambiguous links abstain. Record cross-page evidence. Preserve front-end records rather than overwriting them. |
| `assemblies.jsonl` | `paper_id,assembly_id,scaffold_box_id,table_id,row_id,label,smiles,source_box_ids,evidence_block_ids,method,status,reason` | One record per attempted row; `method=r_group_assembly`. Add `substituents` to preserve cell text and attachment interpretation. |

`gate` and `status` differ: a molecule candidate can pass detection but remain
unreadable. In readings, links, tables and assemblies, `ok` means the intended
result exists, `abstain` means no confident result, and `error` means processing
failed. An `ok` reading can still be a fragment with `*`; valid chemistry does
not establish a complete molecule. Stubs create no fake per-region records.

## Export and scoring

Keep `predictions.csv` columns
`paper_id,smiles,page,x0,y0,x1,y1,label,source,confidence,box_id`.
Add `prediction_id,method,evidence_id` for traceability (the scorer ignores extra
columns). `evidence_id` identifies a reading `(box_id,reader)` or an assembly ID.
`provenance.jsonl` maps prediction IDs to all contributing boxes, cells and text
blocks. An assembly's CSV location is its scaffold; provenance retains evidence
on other pages. Do not invent one box spanning several pages.

Export only the selected reader/consensus result for a complete drawing and
successful full-molecule assemblies. Preserve raw readings; export RDKit
`MolToSmiles` with defaults, without salt stripping, stereo removal or tautomer
standardization. Record parse failures and unresolved wildcards separately in
`export_rejections.jsonl` (`paper_id,evidence_id,reason,raw`). Abstentions have no
prediction row but remain counted in metadata. Never select using the answer key.

The scorer accepts `source=drawing/name/text/unknown`: use `drawing` for image
readings, `text` for a SMILES printed in the paper, and `name` for an external
compound-name lookup. Mixed drawing/table assembly uses `source=unknown` plus
`method=r_group_assembly` and full provenance, so text substituents are not
misrepresented as drawings. Name lookup is disabled in this design. A new
`assembled` source enum would need a separate shared-scorer change. Duplicate
evidence rows can remain; the scorer deduplicates canonical SMILES per paper and
also reports raw output counts.

Keep baseline and filtered runs separate: compare the existing all-candidate
reader baseline with the gate, consensus, label linking and assembly as ablations.
Report rejection/output counts. Patent detection accuracy does not establish
journal detection accuracy. Internal challenge tags remain unfinished (#67); use
paper-level analysis until reviewed. These six papers have already informed the
design, so call them a development benchmark; reserve genuinely unseen papers or
a declared untouched subset for generalization claims.

## Integration and decisions

1. Confirm owners, export responsibility and the boundary between Peter's table
   geometry extraction and Will's assembly module.
2. Each owner supplies a small input/output fixture including an abstention or
   failure with the Oct 28 module paragraph. Cover a complete drawing, an R-group
   row and a non-molecule region.
3. Replace stubs one at a time, preserving IDs/evidence. Test rotated pages,
   missing text, ambiguous labels and reader disagreements.
4. Keep conflicting ML environments separate, exchange these files, and score in
   the shared pinned environment. Preserve a CPU path; document GPU-only readers.
5. Run all six PDFs and inspect errors by paper. Review this proposal together
   before treating it as an agreed contract.

Open choices: gate and consensus policies, table detector, cross-page tables,
canonical versus original prediction text, and a future assembled-source enum.

## AI disclosure

AI tool(s) used: Codex. Purpose: proposed interfaces and integration design.
Specific contribution: Codex drafted the contract after inspecting the repo's
reader/scorer. Team confirmation and scientific review remain pending.
