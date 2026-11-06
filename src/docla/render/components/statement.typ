// Statement slide: one title in a fixed frame.

#import "/lib/marks.typ": section, el, fit-box
#import "/lib/theme.typ": colour, type-style
#import "/lib/frames.typ": content-frame
#import "/lib/cite.typ": cite-keys

#let statement(sec) = section(sec.id, {
  set text(fill: colour("ink"))
  place(top + left, dx: content-frame.x, dy: content-frame.y, fit-box("title", sec.id, content-frame.w, 300pt, {
    set text(..type-style("slides", "figure"))
    if sec.items.len() > 0 { el("title", sec.id, sec.title) } else { sec.title }
    for (i, item) in sec.items.enumerate() {
      parbreak()
      set text(..type-style("slides", "body"))
      let citations = sec.at("citations", default: ()).at(i, default: ())
      el("item", sec.id, [#item.body#if citations.len() > 0 { [ #cite-keys(citations)] }])
    }
  }))
})
