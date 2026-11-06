#import "/lib/marks.typ": section, el
#set page(width: 960pt, height: 540pt, margin: 40pt)
#section("s1", {
  set block(above: 0pt, below: 0pt)
  el("figure", "s1", block(width: 800pt, height: 200pt))
  v(100pt)
  el("figure-source", "s1", [Source: Company records])
})
