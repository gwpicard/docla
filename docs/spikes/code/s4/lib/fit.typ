#let fit-box(role, sec-id, w, h, body) = context {
  let m = measure(block(width: w, body))
  [#metadata((kind: "fit", role: role, id: sec-id, need: m.height / 1pt, have: h / 1pt, ok: m.height <= h)) <doclo-fit>]
  block(width: w, height: h, clip: false, body)
}
