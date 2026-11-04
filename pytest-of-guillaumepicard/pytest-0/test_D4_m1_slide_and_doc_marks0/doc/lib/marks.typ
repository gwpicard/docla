// Marks: metadata labelled <docla-mark>, told apart by `kind`.
// Positions are in pt as numbers.

#import "theme.typ": colour

#let _pos() = {
  let p = here().position()
  (page: p.page, x: p.x / 1pt, y: p.y / 1pt)
}

#let section(id, body) = {
  context [#metadata((kind: "section", id: id, edge: "start", .._pos())) <docla-mark>]
  body
  context [#metadata((kind: "section", id: id, edge: "end", .._pos())) <docla-mark>]
}

// The body always sits in a block, so the mark reports the top edge, not a baseline.
#let el(role, sec-id, body, width: auto) = context {
  let b = block(width: width, body)
  let m = measure(b)
  [#metadata((kind: "element", role: role, id: sec-id, .._pos(), w: m.width / 1pt, h: m.height / 1pt)) <docla-mark>]
  b
}

// `el` measures outside any container, where 100% resolves to 0, so pass the available width.
#let el-full-width(role, sec-id, body) = layout(size => el(role, sec-id, width: size.width, body))

#let fit-box(role, sec-id, w, h, body) = context {
  let m = measure(block(width: w, body))
  [#metadata((kind: "fit", role: role, id: sec-id, need: m.height / 1pt, have: h / 1pt, ok: m.height <= h)) <docla-mark>]
  block(width: w, height: h, clip: true)[
    #body
    #if m.height > h {
      place(bottom, rect(width: w, height: 3pt, fill: colour("accent"), stroke: none))
    }
  ]
}
