#let _pos() = {
  let p = here().position()
  (page: p.page, x: p.x / 1pt, y: p.y / 1pt)
}

#let section(id, body) = {
  context [#metadata((kind: "section", id: id, edge: "start", .._pos())) <docla-mark>]
  body
  context [#metadata((kind: "section", id: id, edge: "end", .._pos())) <docla-mark>]
}

#let el(role, sec-id, body, width: auto) = context {
  let b = block(width: width, body)
  let m = measure(b)
  [#metadata((kind: "element", role: role, id: sec-id, w: m.width / 1pt, h: m.height / 1pt, .._pos())) <docla-mark>]
  b
}

#let row-mark(sec-id, n) = context [#metadata((kind: "row", id: sec-id, n: n, .._pos())) <docla-mark>]
